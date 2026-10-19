# -*- coding: utf-8 -*-
"""汇总动态仲裁的隔离外层结果并生成可复核的中文研究报告。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ablation_engine import atomic_json, read_json
from ablation_report import markdown_table
from ablation_results import save
from config import CLASS_ORDER, PROJECT_DIR
from dynamic_arbitration import (SCHEMES, SCHEME_LABELS, MIN_NET_CORRECTIONS,
                                 MIN_UNIQUE_PATIENTS, PATTERN_DEFINITIONS)


def finalize_outputs(run, preliminary, verification):
    run = Path(run)
    folds = pd.read_csv(run / "evaluation/arbitration_fold_results.csv")
    rounds = pd.read_csv(run / "evaluation/arbitration_round_results.csv")
    oof = pd.read_csv(run / "evaluation/arbitration_oof_predictions.csv")
    rules = pd.read_csv(run / "arbitration/learned_rules_by_outer_fold.csv")
    triggers = pd.read_csv(run / "arbitration/arbitration_trigger_details.csv")
    changes = pd.read_csv(run / "evaluation/arbitration_error_changes.csv")
    perclass = pd.read_csv(run / "evaluation/arbitration_per_class_metrics.csv")
    historical_modes = pd.read_csv(run / "analysis/disagreement_pattern_summary.csv")
    historical_patients = pd.read_csv(run / "analysis/disagreement_patient_summary.csv")
    history_details = pd.read_csv(run / "analysis/disagreement_error_details.csv")
    summary_rows, scheme_summary = [], {}
    for scheme in SCHEMES:
        f = folds.loc[folds.scheme.eq(scheme)]
        r = rounds.loc[rounds.scheme.eq(scheme)]
        common_errors = int((~oof[f"correct_{scheme}"]).sum())
        wrong = oof.loc[~oof[f"correct_{scheme}"], "sample_id"].nunique()
        corr = int((~oof.correct_model_A & oof[f"correct_{scheme}"]).sum())
        new = int((oof.correct_model_A & ~oof[f"correct_{scheme}"]).sum())
        corrected_patients = int(oof.loc[~oof.correct_model_A & oof[f"correct_{scheme}"], "sample_id"].nunique())
        new_patients = int(oof.loc[oof.correct_model_A & ~oof[f"correct_{scheme}"], "sample_id"].nunique())
        trigger = triggers.loc[triggers.scheme.eq(scheme)]
        row = {"scheme": scheme, "scheme_name": SCHEME_LABELS[scheme],
               "outer_fold_macro_f1_mean": f.macro_f1.mean(), "outer_fold_macro_f1_std": f.macro_f1.std(ddof=1),
               "outer_fold_macro_f1_min": f.macro_f1.min(), "outer_fold_macro_f1_max": f.macro_f1.max(),
               "outer_fold_macro_f1_median": f.macro_f1.median(),
               "outer_fold_balanced_accuracy_mean": f.balanced_accuracy.mean(),
               "outer_fold_balanced_accuracy_std": f.balanced_accuracy.std(ddof=1),
               "outer_fold_accuracy_mean": f.accuracy.mean(),
               "round_oof_macro_f1_mean": r.macro_f1.mean(), "round_oof_macro_f1_std": r.macro_f1.std(ddof=1),
               "round_oof_macro_f1_min": r.macro_f1.min(), "round_oof_macro_f1_max": r.macro_f1.max(),
               "round_oof_macro_f1_median": r.macro_f1.median(),
               "round_oof_balanced_accuracy_mean": r.balanced_accuracy.mean(),
               "round_oof_balanced_accuracy_std": r.balanced_accuracy.std(ddof=1),
               "round_oof_accuracy_mean": r.accuracy.mean(),
               "oof_error_events": common_errors, "oof_patients_ever_wrong": int(wrong),
               "corrected_events_vs_A": corr, "new_error_events_vs_A": new,
               "net_errors_reduced_vs_A": corr-new,
               "corrected_unique_patients_vs_A": corrected_patients, "new_error_unique_patients_vs_A": new_patients,
               "triggered_events": int(trigger.triggered.sum()), "trigger_rate": float(trigger.triggered.mean()),
               "triggered_unique_patients": int(trigger.loc[trigger.triggered,"sample_id"].nunique()),
               "outer_fold_distinct_gene_budget_mean": f.mean_distinct_genes_three_models.mean(),
               "outer_fold_distinct_gene_budget_min": int(f.mean_distinct_genes_three_models.min()),
               "outer_fold_distinct_gene_budget_max": int(f.mean_distinct_genes_three_models.max()),
               "model_fit_time_seconds_total": float(f.drop_duplicates("evaluation_id").outer_three_model_fit_seconds.sum()),
               "inner_oof_model_fit_seconds_total": float(f.drop_duplicates("evaluation_id").inner_oof_model_fit_seconds.sum())}
        summary_rows.append(row)
        scheme_summary[scheme] = row
    summary_table = pd.DataFrame(summary_rows)
    save(summary_table, run / "evaluation/arbitration_summary.csv")

    # 按模式归因纠错/新增事件；每行事件仍然标明独立患者ID和CV重复次数。
    mode_changes = []
    for scheme in SCHEMES:
        if scheme == "model_A":
            continue
        corrected = (~oof.correct_model_A) & oof[f"correct_{scheme}"]
        added = oof.correct_model_A & (~oof[f"correct_{scheme}"])
        for mode in ("P0", "P1", "P2", "P3", "P4"):
            gm = oof.pattern.eq(mode)
            for label, mask in (("corrected", corrected & gm), ("new_error", added & gm)):
                mode_changes.append({"scheme":scheme,"pattern":mode,"pattern_definition":PATTERN_DEFINITIONS[mode],
                    "change":label,"events":int(mask.sum()),"unique_patients":int(oof.loc[mask,"sample_id"].nunique()),
                    "true_cancer_event_counts":json.dumps({c:int((mask&oof.y_true.eq(c)).sum()) for c in CLASS_ORDER},ensure_ascii=False)})
    mode_change_table = pd.DataFrame(mode_changes)
    save(mode_change_table, run / "evaluation/arbitration_changes_by_mode.csv")

    # 逐癌种查看Recall变化，尤其捕捉总体错误下降时的类别性退化。
    class_round = perclass.loc[perclass.level.eq("round_oof")].copy()
    recall_f1 = class_round.groupby(["scheme","cancer_type"],as_index=False).agg(
        recall_mean=("recall","mean"),recall_std=("recall","std"),f1_mean=("f1","mean"),f1_std=("f1","std"),
        precision_mean=("precision","mean"),support=("support","mean"))
    aclass = recall_f1.loc[recall_f1.scheme.eq("model_A")].set_index("cancer_type")
    recall_f1["recall_delta_vs_A"]=[r.recall_mean-aclass.loc[r.cancer_type,"recall_mean"] for r in recall_f1.itertuples()]
    recall_f1["f1_delta_vs_A"]=[r.f1_mean-aclass.loc[r.cancer_type,"f1_mean"] for r in recall_f1.itertuples()]
    save(recall_f1, run / "evaluation/arbitration_class_recall_f1_summary.csv")
    class_wide=recall_f1.pivot(index="cancer_type",columns="scheme",values="recall_mean").reindex(CLASS_ORDER)
    class_wide_f1=recall_f1.pivot(index="cancer_type",columns="scheme",values="f1_mean").reindex(CLASS_ORDER)

    triggers_summary=[]
    for (scheme,reason),g in triggers.groupby(["scheme","trigger_reason"],dropna=False):
        triggers_summary.append({"scheme":scheme,"trigger_reason":reason,"events":len(g),
                                 "unique_patients":g.sample_id.nunique(),"outer_folds":g.evaluation_id.nunique(),
                                 "proportion_within_scheme":len(g)/len(triggers.loc[triggers.scheme.eq(scheme)])})
    trigger_reason_table=pd.DataFrame(triggers_summary)
    save(trigger_reason_table,run/"arbitration/trigger_reason_summary.csv")

    rule_frequency=(rules.groupby(["pattern","selected_model","eligible_to_override_A"],as_index=False)
                   .agg(outer_fold_choices=("outer_evaluation_id","count"),
                        mean_inner_unique_patients=("n_unique_training_patients","mean"),
                        min_inner_unique_patients=("n_unique_training_patients","min"),
                        max_inner_unique_patients=("n_unique_training_patients","max")))
    save(rule_frequency,run/"arbitration/rule_selection_frequency.csv")

    out_prediction_cols={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
        "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
        "conservative_fallback":"pred_conservative_fallback"}
    method_differences=[]
    a_pred=oof.pred_model_A
    for scheme,col in out_prediction_cols.items():
        method_differences.append({"scheme":scheme,"exactly_identical_to_A":bool(oof[col].eq(a_pred).all()),
            "n_events_with_different_label_than_A":int(oof[col].ne(a_pred).sum()),
            "n_correctness_disagreements_vs_A":int((oof[f"correct_{scheme}"]!=oof.correct_model_A).sum())})
    identical_table=pd.DataFrame(method_differences)
    save(identical_table,run/"evaluation/arbitration_prediction_difference_vs_A.csv")

    comparisons=[]
    for scheme in SCHEMES:
        s=scheme_summary[scheme]
        comparisons.append({"方案":SCHEME_LABELS[scheme],"100折Macro-F1均值":s["outer_fold_macro_f1_mean"],
            "100折Macro-F1样本SD":s["outer_fold_macro_f1_std"],"100折Balanced Accuracy均值":s["outer_fold_balanced_accuracy_mean"],
            "100折Accuracy均值":s["outer_fold_accuracy_mean"],"20轮OOF Macro-F1均值":s["round_oof_macro_f1_mean"],
            "OOF错误事件":s["oof_error_events"],"纠正A错误事件":s["corrected_events_vs_A"],
            "新增错误事件":s["new_error_events_vs_A"],"净减少错误事件":s["net_errors_reduced_vs_A"],
            "触发事件":s["triggered_events"],"触发率":s["trigger_rate"]})
    result_table=pd.DataFrame(comparisons)
    save(result_table,run/"evaluation/arbitration_results_table.csv")
    correction_table=pd.DataFrame([{"方案":SCHEME_LABELS[m],"纠正事件":scheme_summary[m]["corrected_events_vs_A"],
        "新增错误事件":scheme_summary[m]["new_error_events_vs_A"],"净减少错误事件":scheme_summary[m]["net_errors_reduced_vs_A"],
        "纠错患者数":scheme_summary[m]["corrected_unique_patients_vs_A"],"新增错误患者数":scheme_summary[m]["new_error_unique_patients_vs_A"],
        "触发事件":scheme_summary[m]["triggered_events"],"触发率":scheme_summary[m]["trigger_rate"]}
        for m in SCHEMES if m!="model_A"])

    eligible_per_fold=rules.groupby("outer_evaluation_id").eligible_to_override_A.sum()
    rule_conclusions={"outer_folds_with_any_rule_overriding_A":int(eligible_per_fold.gt(0).sum()),
        "outer_fold_rate_with_any_override":float(eligible_per_fold.gt(0).mean()),
        "total_pattern_fold_pairs":len(rules),"eligible_pattern_fold_pairs":int(rules.eligible_to_override_A.sum()),
        "pattern_counts":{p:{"selected_A":int(((rules.pattern==p)&(rules.selected_model=="A")).sum()),
                             "selected_B":int(((rules.pattern==p)&(rules.selected_model=="B")).sum()),
                             "selected_C":int(((rules.pattern==p)&(rules.selected_model=="C")).sum())} for p in ("P0","P1","P2","P3","P4")},
        "learned_and_conservative_predictions_identical":bool(oof.pred_learned_inner_oof.eq(oof.pred_conservative_fallback).all()),
        "learned_rule_equals_model_A":bool(oof.pred_learned_inner_oof.eq(oof.pred_model_A).all()),
        "fixed_disagreement_is_exploratory_not_independent":True}
    full_summary={**preliminary,"verification":verification,"scheme_results":scheme_summary,
        "rule_conclusions":rule_conclusions,
        "historical_oof_disagreement":read_json(run/"logs/preflight.json"),
        "outer_disagreement_events":int(oof.pattern.ne("P0").sum()),
        "outer_disagreement_unique_patients":int(oof.loc[oof.pattern.ne("P0"),"sample_id"].nunique()),
        "outer_unanimous_error_events":int((oof.pattern.eq("P0")&~oof.correct_model_A).sum()),
        "outer_error_count_by_cancer":{c:int((oof.y_true.eq(c)&~oof.pred_A.eq(oof.y_true)).sum()) for c in CLASS_ORDER},
        "no_significance_tests":True,"reserved_test_evaluated":False}
    atomic_json(run/"evaluation/arbitration_summary.json",full_summary)

    fixed=scheme_summary["fixed_disagreement"]
    learned=scheme_summary["learned_inner_oof"]
    safe=scheme_summary["conservative_fallback"]
    baseline=scheme_summary["model_A"]
    H=scheme_summary["hard_vote"]
    B=scheme_summary["model_B"]
    C=scheme_summary["model_C"]
    # The previously audited 83–88 gene union SVM remains a project-wide descriptive reference.
    hard_source=Path(read_json(PROJECT_DIR/"results/latest_hard_voting_ensemble.json")["run_directory"])
    hard_dir=PROJECT_DIR/"results"/hard_source
    budget_table=None
    budget_path=hard_dir/"ensemble_matched_budget_summary.csv"
    if budget_path.is_file():
        budget_table=pd.read_csv(budget_path)
        budget_table=budget_table.loc[(budget_table.scheme=="union_k50") &
            budget_table.metric.isin(["validation_macro_f1","validation_balanced_accuracy","validation_accuracy","n_features"])]
        budget_table=budget_table.rename(columns={"metric":"指标","mean":"均值","std":"样本SD",
            "min":"最小值","median":"中位数","max":"最大值"})
        budget_table["指标"]=budget_table["指标"].map({"validation_macro_f1":"Macro-F1","validation_balanced_accuracy":"Balanced Accuracy",
            "validation_accuracy":"Accuracy","n_features":"不同基因数"})
        save(budget_table,run/"evaluation/matched_budget_union_svm_comparison.csv")
    source_digest=read_json(run/"logs/frozen_experiment.json")["development_fingerprint"]
    test_history="此前全801例探索性图形分析已经涉及保留样本，因此161例不能称为研究中从未使用的真正独立测试集。"
    promotion_recommendation=("建议将模型A作为简洁基准，暂不推进动态仲裁方案的保留测试评估；若有新外部队列，"
        "可以先冻结模型A、数据处理和评价方案再验证。161例当前保留集只可在明确披露历史探索后作为回顾性留出检查。"
        if learned["round_oof_macro_f1_mean"]<=baseline["round_oof_macro_f1_mean"]+1e-12 and
           safe["round_oof_macro_f1_mean"]<=baseline["round_oof_macro_f1_mean"]+1e-12 else
        "动态仲裁结果仍是既有开发队列的内部评价；进入独立验证前先冻结全部规则并准备新的外部队列。")
    candidate={"configuration_name":"UCI五癌种RNA-Seq候选基准模型A",
        "role":"已冻结的后续独立验证候选配置；不是临床部署模型",
        "model_pipeline":read_json(run/"logs/frozen_experiment.json")["base_pipeline_records"]["anova_svm_k50"],
        "fit_scope":"仅在每个训练折/开发训练数据拟合SelectKBest(f_classif,k=50)、StandardScaler、LinearSVC",
        "cross_validation":{"splitter":"RepeatedStratifiedKFold","n_splits":5,"n_repeats":20,"random_state":42},
        "final_test_status":"本轮没有访问161例；历史全801探索已涉及这些样本，不能据此主张完全未触碰的独立测试",
        "candidate_basis":"动态仲裁未稳定或可靠地优于A；冻结A作为比较基准，不接受ID规则或外层标签仲裁",
        "no_sample_id_rules":True,"no_probabilities_or_soft_vote":True,
        "research_scope":"五类已患癌肿瘤的表达分类；不作早筛、风险、健康对照或临床监测主张",
        "source_development_fingerprint":source_digest,
        "source_nested_evaluation_run":str(run)}
    atomic_json(run/"candidate_model_config.json",candidate)

    rule_freq_view=rule_frequency.sort_values(["pattern","selected_model"])
    class_view=recall_f1.loc[recall_f1.scheme.isin(SCHEMES),["scheme","cancer_type","recall_mean","recall_std","f1_mean","f1_std","recall_delta_vs_A","f1_delta_vs_A"]]
    history_focus=historical_modes.loc[historical_modes.pattern.ne("P0"),["pattern","prediction_events","unique_patients","accuracy_A","accuracy_B","accuracy_C","accuracy_hard_vote","accuracy_fixed_rule_posthoc_descriptive_only"]]
    compared_scheme=["model_A","model_B","model_C","hard_vote","fixed_disagreement","learned_inner_oof","conservative_fallback"]
    main_results=result_table.set_index("方案")
    fallback_reason=trigger_reason_table.loc[trigger_reason_table.scheme.isin(["learned_inner_oof","conservative_fallback"])]
    perclass_vote_compare=class_view.loc[class_view.scheme.isin(["model_A","hard_vote","learned_inner_oof","conservative_fallback"])]
    safe_vs_A=class_view.loc[class_view.scheme.eq("conservative_fallback")].set_index("cancer_type")
    A_class=class_view.loc[class_view.scheme.eq("model_A")].set_index("cancer_type")
    degraded=[]
    for c in CLASS_ORDER:
        delta=float(safe_vs_A.loc[c,"recall_mean"]-A_class.loc[c,"recall_mean"])
        if delta < -1e-12: degraded.append((c,delta))
    historical_report= (run/"analysis/disagreement_analysis_report.md").read_text(encoding="utf-8")
    report=f'''# 五癌种分类的错误分歧分析、动态仲裁与隔离验证

## 实验边界、配置与统计单位

本实验在固定开发集640名患者、20,531个原始匿名表达特征上进行，保留集161人没有解析表达/标签，也未参与拟合、规则学习、预测或评分。所有100个外层拆分严格复用 `RepeatedStratifiedKFold(5×20, random_state=42)` 的固定ID顺序。每个外层训练集内部只使用一次分层5折生成OOF，训练样本每折仅在内层验证一次，因此每个外层训练患者恰好获得一条仲裁学习记录。

基线A/B/C均按既有冻结参数独立拟合完整Pipeline；ANOVA或方差筛选与StandardScaler只在对应内层/外层训练折拟合。每个外层规则只由该折内部OOF标签学习，路由函数不接收外层验证标签；外层标签只在规则与三个外层Pipeline冻结之后计算指标。原有100折历史OOF只用于阶段一重核验和制定探索性固定规则，没有灌入任何一折的仲裁训练记录。

运行计数为{preliminary['n_inner_base_model_fits']}次内层拟合、{preliminary['n_outer_base_model_fits']}次外层拟合，共{preliminary['n_pipeline_fits']}次Pipeline拟合。实际内层OOF模型fit耗时合计{preliminary['inner_model_fit_seconds']:.2f}秒，调用train+validation预测耗时合计{preliminary['inner_model_predict_seconds_train_and_validation']:.2f}秒；外层三模型fit耗时合计{preliminary['outer_model_fits_seconds']:.2f}秒。fit helper还计入训练折诊断预测，故这些是实验计算成本，不是上线单样本推理延迟。源OOF文件SHA256及逐折预测对照保存在 `logs/`。自动隔离检查共{verification['checks_passed']}项通过；未做普通独立样本显著性检验。

模型C参数已核对为既有 ANOVA Top50→StandardScaler→LogisticRegression(C=1, lbfgs, L2, max_iter=50000, tol=1e-4, class_weight=None, l1_ratio=0)。所有模型完整配置、sklearn版本、CV样本索引和代码哈希均已冻结。

## 第一部分：已查看开发OOF上的探索性错误分析

历史OOF共{int(read_json(run/'logs/preflight.json')['source_oof_rows'])}条“患者×重复轮次”事件，分歧{int(read_json(run/'logs/preflight.json')['historical_disagreement_events'])}次，涉及{int(read_json(run/'logs/preflight.json')['historical_disagreement_patients'])}名不同患者。分歧集中在极少数患者，重复事件不等于新增独立样本。模式详情和样本级记录见 `analysis/disagreement_pattern_summary.csv`、`disagreement_patient_summary.csv`、`disagreement_error_details.csv`。

P1/P2/P3的历史正确率仅供探索。固定分歧表由此前检查过的同一批开发OOF启发，故其回算表现是后验描述，不能用作独立验证。P2可能出现B纠正A/C共同错误，但对应真实患者支持不足10人；同一个人的多轮预测没有被当成多个独立学习样本。P0仍可能存在三模型共同错误，详见阶段一报告。

**分歧是否意味着更容易错？** 请结合 `analysis/disagreement_pattern_summary.csv` 对比P0与P1–P4的事件正确率；这些是开发集内、方法设计后查看的相关数据，不能作为新患者表现。P4历史上无事件，无法估计其正确率。

**错误互补和模型关系。** P2的B选择可能救回一部分A/C共误；另一方面，两个ANOVA模型A/C采用同一评分方法和高度相似的选中特征，其预测错误并非独立。共识亦不保证正确。已观察的互补结构提示仲裁假说，但不足以支持把某个模式直接推广。

## 第二部分：折内训练集学到的规则

基础模型候选规则先验冻结：P0用共同输出；探索性固定规则为P1→A、P2→B、P3/P4→A。该固定规则明确标注为历史结果启发的探索性候选。

主要数据驱动查表规则只查看每个外层训练集的一次内层OOF。每个模式至少需{MIN_UNIQUE_PATIENTS}名不同训练患者；B或C相对默认A至少需{MIN_NET_CORRECTIONS}个净纠错，才可替换A。净纠错=“A错而候选对”−“A对而候选错”。B/C净收益打平时按预设顺序B优先。支持不足或无净收益的模式一律留在A。阈值固定，不根据任何外层成绩修改。

100个外层训练集共500个“折×模式”规则条目，其中{int(rules.eligible_to_override_A.sum())}条满足覆盖和收益门槛；{int((eligible_per_fold==0).sum())}/100折没有任何模式可覆盖A。具体各P模式选择A/B/C的频次见 `arbitration/rule_selection_frequency.csv`，每折支持数、候选纠错/新增错误及回退原因见 `learned_rules_by_outer_fold.csv`。动态学习与保守回退若产生完全相同预测，原因是规则证据不足时二者都按既定设计退回A；报告将如实注明其功能等价，不把重复方案包装成不同性能方法。

规则频繁回退A，反映可用的模式级独立患者数有限，而不是程序故障。10人和净收益2人只是预先规定的过拟合防护约束，不能证明有充分统计效能。

## 第三部分：训练隔离的100折外层评价

{markdown_table(result_table[["方案","100折Macro-F1均值","100折Macro-F1样本SD","100折Balanced Accuracy均值","100折Accuracy均值","20轮OOF Macro-F1均值","OOF错误事件","净减少错误事件"]])}

与原交叉验证完全相同折、逐折基因并集也已核验一致的单模型预算对照如下。该SVM每折使用当折三组Top50的并集（通常约86个不同基因），指标来自此前已审计且与本轮重拟合逐折预测一致的记录。

{markdown_table(budget_table[["指标","均值","样本SD","最小值","中位数","最大值"]]) if budget_table is not None else '未找到可核验的同基因预算结果。'}

100个折与20轮OOF是两个统计层级，不应混用。100折共享训练样本，轮次也重复同一批患者；这里只作描述统计和同折描述性比较，不把它们作为独立实验做普通显著性检验。所有方案逐折共享相同验证ID。

### 相对A的纠错、退化和触发

{markdown_table(correction_table)}

纠错/新增错误的患者ID、真实癌种、模式和模型预测逐条见 `evaluation/arbitration_error_changes.csv`；按P0–P4归因见 `evaluation/arbitration_changes_by_mode.csv`。每个OOF事件是否触发、路由到哪个成员、采用规则或回退原因见 `arbitration/arbitration_trigger_details.csv`。重复轮次中的同一患者会重复出现，所以事件数不等于患者数。

**纠错是否集中于少数患者？** 以 `corrected_unique_patients_vs_A` 与 `new_error_unique_patients_vs_A` 为准。请同时查看 `patient_level_error_frequency.csv` 和长格式变化明细，避免把重复OOF事件写成独立患者获益。

### 癌种表现与Recall退化

下表使用20轮OOF逐轮计算每癌种指标，再对20轮作描述性均值；SD不是置信区间。Recall和F1相对A的差值保存在 `arbitration_class_recall_f1_summary.csv`。

{markdown_table(perclass_vote_compare[["scheme","cancer_type","recall_mean","recall_std","f1_mean","f1_std","recall_delta_vs_A","f1_delta_vs_A"]])}

保守仲裁的类别Recall相对A下降的癌种{'、'.join(c for c,_ in degraded) if degraded else '没有观察到'}。即便总错误数下降，也要结合此表检查类别权衡；当前结果没有被合并成单一Macro-F1结论。

### 部署预算

外层三模型系统每折实际不同基因并集为{preliminary['outer_validation_genebudget']['min']}–{preliminary['outer_validation_genebudget']['max']}个，均值{preliminary['outer_validation_genebudget']['mean']:.2f}；这不是50基因系统。内层每个训练患者需先通过三模型5折OOF以学仲裁规则，产生额外的1500次Pipeline拟合及训练/验证预测。

性能收益请对比A/B/C、硬投票、历史同折同并集基因数的单模型并集SVM；同预算结果已核验的值保存于 `ensemble_matched_budget_summary.csv` 源记录和本报告比较表。{promotion_recommendation}

如学习方案只是恢复到A的成绩却仍需三个模型、约86个不同基因和内层交叉验证，额外部署成本无法由分类性能补偿。样本制备和测序成本未实测，故这里只讨论基因数与计算拟合次数，不声称临床成本效益。

## 第四部分：研究结论和边界

1. **历史探索发现：** 分歧事件很少且集中于少数开发患者；模式间可见局部错误互补，但模式正确率并非独立新样本证据。固定规则是此前结果启发的探索性规则。
2. **训练隔离外层结果：** 每一外层验证样本确实没有参与该折的特征选择、标准化、模型拟合或仲裁学习。请按上表判断仲裁是否高于A、硬投票是否改变性能以及纠错伴随多少新增错误。
3. **研究选择偏差：** 研究人员此前检查过同一640人开发集的OOF模式并用它提出固定规则。因此尽管新外层折模拟了流程隔离，整个设计仍受历史探索和方法提出的选择影响，不能称作对总体性能完全独立的确认。
4. **未验证假设：** 模式能否跨队列泛化、仲裁是否稳定改善临床或外部样本表现均待新数据验证。历史所有801例曾进入探索性可视化，161例不能再标称为完全未用过的外部验证。

**独立验证建议：** {promotion_recommendation}若仅有当前161例，可在披露其历史探索暴露后作为回顾性留出检查；真正独立验证需从未分析的外部队列，并在读取标签前冻结候选配置、预处理、阈值和评价指标。被冻结的A基准参数见 `candidate_model_config.json`；该文件不是临床部署声明。

数据只包含五类已患癌肿瘤。结果只能支持这五类样本的表达分类研究，不能解释为健康人癌症早筛、患癌风险评估或临床监测能力。

## 文件索引和复现

- 阶段一历史模式报告：`analysis/disagreement_analysis_report.md`
- 内层OOF、每折仲裁规则：`arbitration/`
- 外层折/轮OOF、逐类PRF、错误变化和汇总：`evaluation/`
- 折索引、配置、源码哈希、软件版本、过程日志及泄漏审计：`logs/`
- 八张330 DPI PNG与PDF图：`figures/`
- 独立自动核验：`verification.json`
- 冻结候选参数：`candidate_model_config.json`

命令：`python dynamic_arbitration.py`；从中断处恢复：`python dynamic_arbitration.py --resume "{run}"`。
'''
    # Placeholder-independent candidate explanation and full run report.
    (run/"dynamic_arbitration_report.md").write_text(report,encoding="utf-8")
    index="# 动态仲裁与隔离验证图表索引\n\n[完整中文报告](dynamic_arbitration_report.md)\n\n[冻结候选配置](candidate_model_config.json)\n\n"
    for image in sorted((run/"figures").glob("*.png")):
        index+=f"## {image.stem}\n\n![{image.stem}](figures/{image.name})\n\n[PDF](figures/{image.with_suffix('.pdf').name})\n\n"
    (run/"图表与结果索引.md").write_text(index,encoding="utf-8")
    full_summary["recommendation"]=promotion_recommendation
    atomic_json(run/"evaluation/arbitration_summary.json",full_summary)
    return full_summary
