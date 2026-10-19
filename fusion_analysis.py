# -*- coding: utf-8 -*-
"""配对开发集预测、互补性描述分析和中文报告；不选择最终模型。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ablation_engine import METRICS, atomic_json, read_json
from ablation_report import markdown_table
from ablation_results import save
from fusion_results import statistics
from fusion_selection import schemes

RULE_LABELS = {"anova": "ANOVA", "variance": "高方差", "fusion_equal": "等比例融合",
               "fusion_anova75": "ANOVA 75%融合", "fusion_variance75": "高方差75%融合",
               "intersection": "交集", "union": "并集", "anova_only": "ANOVA独有", "variance_only": "高方差独有",
               "anova_matched_union": "ANOVA匹配M", "variance_matched_union": "高方差匹配M", "add_variance": "ANOVA50+高方差补充"}


def contrasts():
    result = []
    for k in (20, 50):
        for rule in ("fusion_equal", "fusion_anova75", "fusion_variance75", "intersection", "union", "anova_only", "variance_only"):
            for reference in (f"anova_k{k}", f"variance_k{k}"):
                result.append((f"{rule}_k{k}", reference, "same_budget" if rule.startswith("fusion") else "variable_budget_exploration"))
        for reference in (f"anova_matched_union_k{k}", f"variance_matched_union_k{k}"):
            result.append((f"union_k{k}", reference, "matched_union_size_each_fold"))
    for increment in (10, 20, 30):
        for reference in ("anova_k50", f"anova_k{50+increment}", f"variance_k{50+increment}"):
            result.append((f"add_variance_{increment}", reference, "size_increase_from_base" if reference == "anova_k50" else "same_budget"))
    return result


def analyze(run):
    fold = pd.read_csv(run / "fusion_cv_fold_results.csv")
    summary = pd.read_csv(run / "fusion_cv_summary.csv")
    oof = pd.read_csv(run / "fusion_oof_predictions.csv")
    round_metrics = pd.read_csv(run / "fusion_cv_round_results.csv")
    stability = pd.read_csv(run / "fusion_feature_stability.csv")
    overlap = pd.read_csv(run / "fusion_feature_overlap.csv")
    errors = pd.read_csv(run / "fusion_sample_errors.csv")
    pair_rows, round_differences, transitions, pair_summary = [], [], [], []
    for target, reference, design in contrasts():
        a = fold.loc[fold.scheme.eq(target) & fold.status.eq("evaluated")]
        b = fold.loc[fold.scheme.eq(reference) & fold.status.eq("evaluated")]
        merged = a.merge(b, on=["evaluation_id", "repeat_id", "fold_id"], suffixes=("_target", "_reference"), validate="one_to_one")
        row = {"target": target, "reference": reference, "comparison_design": design, "n_paired_folds": len(merged)}
        rm = round_metrics.loc[round_metrics.scheme.eq(target) & round_metrics.status.eq("complete")].merge(
            round_metrics.loc[round_metrics.scheme.eq(reference) & round_metrics.status.eq("complete")], on="repeat_id", suffixes=("_target", "_reference"), validate="one_to_one")
        row["n_paired_rounds"] = len(rm)
        if len(rm):
            delta_round = rm.oof_macro_f1_target - rm.oof_macro_f1_reference
            row.update(statistics(delta_round, "delta_round_oof_macro_f1_"))
            row.update(n_better_rounds=int((delta_round > 1e-12).sum()), n_worse_rounds=int((delta_round < -1e-12).sum()), n_tied_rounds=int((delta_round.abs() <= 1e-12).sum()))
            round_differences.extend({"target": target, "reference": reference, "comparison_design": design, "repeat_id": r.repeat_id,
                                      **{f"delta_oof_{m}": getattr(r, f"oof_{m}_target") - getattr(r, f"oof_{m}_reference") for m in METRICS}}
                                     for r in rm.itertuples())
        for m in METRICS:
            delta = merged[f"validation_{m}_target"] - merged[f"validation_{m}_reference"]
            row.update(statistics(delta, f"delta_{m}_"))
            if m == "macro_f1":
                row.update(n_better_folds=int((delta > 1e-12).sum()), n_worse_folds=int((delta < -1e-12).sum()), n_tied_folds=int((delta.abs() <= 1e-12).sum()))
        for r in merged.itertuples():
            pair_rows.append({"target": target, "reference": reference, "comparison_design": design,
                              "evaluation_id": r.evaluation_id, "repeat_id": r.repeat_id, "fold_id": r.fold_id,
                              "target_n_features": r.n_features_target, "reference_n_features": r.n_features_reference,
                              **{f"delta_{m}": getattr(r, f"validation_{m}_target") - getattr(r, f"validation_{m}_reference") for m in METRICS}})
        ap, bp = oof.loc[oof.scheme.eq(target)], oof.loc[oof.scheme.eq(reference)]
        predictions = ap.merge(bp, on=["evaluation_id", "repeat_id", "fold_id", "sample_id"], suffixes=("_target", "_reference"), validate="one_to_one")
        assert np.array_equal(predictions.y_true_target, predictions.y_true_reference)
        rescued = predictions.is_error_reference & ~predictions.is_error_target
        regressed = ~predictions.is_error_reference & predictions.is_error_target
        row.update(n_paired_predictions=len(predictions), n_error_predictions_reference=int(predictions.is_error_reference.sum()),
                   n_error_predictions_target=int(predictions.is_error_target.sum()), n_rescued_predictions=int(rescued.sum()),
                   n_new_error_predictions=int(regressed.sum()), n_patients_rescued=predictions.loc[rescued, "sample_id"].nunique(),
                   n_patients_new_error=predictions.loc[regressed, "sample_id"].nunique())
        pair_summary.append(row)
        changed = predictions.loc[rescued | regressed]
        transitions.extend({"target": target, "reference": reference, "comparison_design": design,
                            "evaluation_id": r.evaluation_id, "repeat_id": r.repeat_id, "fold_id": r.fold_id,
                            "sample_id": r.sample_id, "y_true": r.y_true_target, "reference_prediction": r.y_pred_reference,
                            "target_prediction": r.y_pred_target, "change": "rescued" if r.is_error_reference else "new_error"}
                           for r in changed.itertuples())
    paired = pd.DataFrame(pair_summary)
    save(pd.DataFrame(pair_rows), run / "fusion_paired_fold_differences.csv")
    save(pd.DataFrame(round_differences), run / "fusion_paired_round_differences.csv")
    save(paired, run / "fusion_paired_summary.csv")
    transition_frame = pd.DataFrame(transitions, columns=["target", "reference", "comparison_design", "evaluation_id", "repeat_id", "fold_id", "sample_id", "y_true", "reference_prediction", "target_prediction", "change"])
    save(transition_frame, run / "fusion_prediction_transitions.csv")
    if len(transition_frame):
        patient_changes = transition_frame.groupby(["target", "reference", "sample_id", "y_true", "change"]).size().unstack("change", fill_value=0).reset_index()
    else:
        patient_changes = pd.DataFrame(columns=["target", "reference", "sample_id", "y_true", "rescued", "new_error"])
    save(patient_changes, run / "fusion_sample_transition_summary.csv")
    overlap_summary = overlap.groupby("k").agg(intersection_mean=("intersection_size", "mean"), intersection_min=("intersection_size", "min"),
        intersection_max=("intersection_size", "max"), union_mean=("union_size", "mean"), union_min=("union_size", "min"), union_max=("union_size", "max"),
        jaccard_mean=("jaccard", "mean"), jaccard_std=("jaccard", "std")).reset_index()
    save(overlap_summary, run / "fusion_feature_overlap_summary.csv")
    joint = summary.merge(stability[["scheme", "jaccard_mean", "jaccard_std", "n_always_selected"]], on="scheme", how="left", validate="one_to_one")
    save(joint, run / "fusion_performance_stability.csv")
    class_errors = errors.groupby(["scheme", "y_true"]).agg(error_count=("error_count", "sum"),
        n_patients_with_error=("error_count", lambda s: int((s > 0).sum()))).reset_index()
    save(class_errors, run / "fusion_errors_by_cancer.csv")
    metrics_columns = ["scheme", "n_features_mean", "n_features_min", "n_features_max", "validation_macro_f1_mean", "validation_macro_f1_std",
                       "validation_balanced_accuracy_mean", "validation_accuracy_mean", "n_empty_folds"]
    fixed = joint.loc[joint.experiment.eq("A")]
    variable = joint.loc[joint.experiment.eq("B")]
    additions = joint.loc[joint.experiment.eq("C") | joint.scheme.eq("anova_k50")]
    direct_improvements = paired.loc[paired.comparison_design.isin(["same_budget", "matched_union_size_each_fold"]) & paired.delta_macro_f1_mean.gt(1e-12)]
    status = read_json(run / "classification_status.json")
    experiment = {**status, "status": "analyzed", "scope": "fixed_640_development_only", "reserved_test_values_or_labels_used": False,
                  "n_schemes": len(schemes()), "n_folds_each_scheme": 100, "n_rounds": 20,
                  "n_shared_subsamples": 30, "stability_classifier_fits": 0,
                  "fixed_budget_results": fixed[metrics_columns + ["jaccard_mean", "jaccard_std"]].to_dict("records"),
                  "variable_budget_results": variable[metrics_columns].to_dict("records"),
                  "addition_results": additions[metrics_columns].to_dict("records"),
                  "paired_comparisons": paired.to_dict("records"), "statistical_tests_performed": False,
                  "final_model_selected": False, "previous_experiment_conclusions_modified": False,
                  "interpretation": "exploratory descriptive comparisons on dependent development CV; no unbiased external generalization claims"}
    # JSON 不写 NaN：空集合导致的未定义统计保留 null。
    import json
    clean = json.loads(json.dumps(experiment, default=lambda v: v.item() if isinstance(v, np.generic) else str(v)))
    def finite(v):
        if isinstance(v, dict):
            return {k: finite(x) for k, x in v.items()}
        if isinstance(v, list):
            return [finite(x) for x in v]
        return None if isinstance(v, float) and not np.isfinite(v) else v
    atomic_json(run / "fusion_experiment_summary.json", finite(clean))
    text = ["# ANOVA与高方差基因特征的互补性及融合消融实验", "", "## 数据与预先固定的设计", "",
            "仅使用原有640开发样本、20531匿名基因。161保留测试样本的表达/标签未解析、未评分。复用完全相同的5折×20轮、seed=42索引，每折训练512、验证128。LinearSVC(C=1,dual='auto',max_iter=50000,tol=1e-4)，StandardScaler只拟合当前训练折。",
            "",
            "31个不同方案在运行前冻结。固定K=20/50下：单ANOVA、单高方差、等比例融合、ANOVA75%主导融合、高方差75%主导融合。配额取最近整数，半数向上；因此K50的75%为38，剩余12；按辅助方法完整排名补足尚未选中的基因，始终恰好K个。所有最终输入列都按原列位置排序。",
            "",
            "另在各训练折构造交集、并集、两种独有集合，并按该折并集大小M建立ANOVA Top-M与高方差Top-M对照。逐步补充固定为ANOVA50加高方差未入选前10/20/30个，和单方法60/70/80比较。未根据错误样本挑选新增基因或调整配额。",
            "",
            f"分类记录：{status}。既有单方法基线在数据指纹、训练/验证样本顺序、参数、数值库版本、选中列和真实训练/验证预测指标一致后复用。历史时间保留原测量值，不能作为同负载速度比较。",
            "", "fit_seconds为实际Pipeline.fit调用耗时；折内评分共享准备不重复分摊到每个模型，因此该时间不代表每方案从原始数据独立重算的端到端成本，不用于算法运行效率结论。",
            "",
            "每个训练折重新计算并保存评分；只复用严格绑定同一训练矩阵、标签顺序、样本ID的折内评分缓存。Pipeline选择器fit核对缓存数值摘要，标准化器和分类器每次从未拟合状态开始。恒定基因ANOVA NaN保留诊断，排序副本置负无穷；其他异常停止。空集合明确记录skipped_empty，不填补特征，不拟合分类器；相应折/轮缺失会明确报告。",
            "", "## 1. 基因集合重合", "", markdown_table(overlap_summary), "",
            "低重合本身只说明选择结果不同，不能证明判别信息互补。", "", "## 2. 固定预算融合性能", "",
            "以下均值/样本SD来自100个相关验证折；完整20轮合并OOF均值、SD及逐癌种报告另存。", "",
            markdown_table(fixed[metrics_columns + ["jaccard_mean", "jaccard_std"]]), "",
            "## 3. 交集、并集和独有特征", "", markdown_table(variable[metrics_columns]), "",
            "各集合数量随训练折变化；交集/独有集合成绩只作探索，不能与固定K直接等预算比较。并集需优先与同折Top-M对照比较，不能将较大集合的改善直接归因于互补性。", "",
            "并集相对匹配M对照的同折差值（目标减参考）：", "",
            markdown_table(paired.loc[paired.comparison_design.eq("matched_union_size_each_fold"), ["target", "reference", "delta_macro_f1_mean", "delta_macro_f1_std", "n_better_folds", "n_worse_folds", "n_tied_folds", "n_rescued_predictions", "n_new_error_predictions"]]), "",
            "## 4. 逐步补充遗漏特征", "", markdown_table(additions[metrics_columns]), "",
            "同样数量的60/70/80单方法对照可帮助判断，高方差补充是否比继续沿ANOVA排名取基因更有价值。与ANOVA50的比较同时改变数量，不能单独识别融合效果。", "",
            "## 5. 配对性能差值与患者错误变化", "",
            markdown_table(paired[["target", "reference", "comparison_design", "delta_macro_f1_mean", "delta_balanced_accuracy_mean", "n_better_folds", "n_worse_folds", "n_rescued_predictions", "n_new_error_predictions"]]), "",
            "每次“救回”或“新增错误”对应同一验证折、同一开发患者的真实OOF预测对照。完整患者ID、轮次、原预测和新预测见fusion_prediction_transitions.csv，按患者汇总见fusion_sample_transition_summary.csv。重复20次不是20个独立患者；救回与新增错误必须同时考虑，不能只报告改善案例。", "",
            "Macro-F1按癌种等权汇总，并同时受各类精确率和召回影响；原始错误次数按患者计数。因此错误次数减少和Macro-F1提高不必然给出相同排序，不能只用其中一项替代全部性能指标。", "",
            "发生预测变化的患者记录示例（最多30行，完整记录保留在上述CSV；若表为空表示无变化）：", "", markdown_table(patient_changes.head(30)), "",
            "## 6. 共享子采样下的稳定性", "",
            "严格复用此前RQ2的30组512样本索引，重新在每个子样本内计算ANOVA和高方差排名，不拟合任何稳定性分类器。每方案435个相互相关集合比较，仅报告描述统计。固定预算与可变集合分别列出，空-空Jaccard定义为未定义而非1。", "",
            "固定预算：", "", markdown_table(stability.loc[stability.fixed_budget, ["scheme", "jaccard_mean", "jaccard_std", "jaccard_median", "jaccard_min", "jaccard_max", "n_always_selected", "n_ever_selected"]]), "",
            "可变预算（不与固定K直接排序得出优劣）：", "", markdown_table(stability.loc[~stability.fixed_budget, ["scheme", "set_size_mean", "set_size_min", "set_size_max", "jaccard_mean", "jaccard_std", "n_empty_sets"]]), "",
            "完整20531基因入选频率包含从未入选者，分母均为30；与单方法同子采样重合另存stability/overlap_with_single_methods.csv。", "",
            "## 7. 研究问题的回答与证据分层", ""]
    for k in (20, 50):
        base = fixed.loc[fixed.k.eq(k)]
        best_single = base.loc[base.rule.isin(["anova", "variance"])].sort_values("validation_macro_f1_mean", ascending=False).iloc[0]
        for r in base.loc[base.rule.str.startswith("fusion")].itertuples():
            text.append(f"- K={k}，{RULE_LABELS[r.rule]}：Macro-F1={r.validation_macro_f1_mean:.8f}，相对该K较高单方法({best_single.scheme})差值={r.validation_macro_f1_mean-best_single.validation_macro_f1_mean:+.8f}；Jaccard={r.jaccard_mean:.6f}。")
    for rule in ("intersection", "anova_only", "variance_only"):
        for r in variable.loc[variable.rule.eq(rule)].itertuples():
            text.append(f"- {RULE_LABELS[rule]}，原K={r.k}：平均实际基因数{r.n_features_mean:.2f}，Macro-F1={r.validation_macro_f1_mean:.8f}，Balanced Accuracy={r.validation_balanced_accuracy_mean:.8f}。是否保留大部分信息仅由这些预测表现描述，不能据此定位因果信息。")
    text += ["", "### 九个研究问题的直接回答", ""]
    text.append("1. **是否选出不同集合**：" + "；".join(f"K={int(r.k)}同折平均Jaccard={r.jaccard_mean:.6f}、平均交集{r.intersection_mean:.2f}个" for r in overlap_summary.itertuples()) + "。这是集合差异的描述，不等同于信息独立或互补。")
    text.append("2. **共同基因的分类能力**：" + "；".join(f"原K={int(r.k)}的交集平均{r.n_features_mean:.2f}基因、Macro-F1={r.validation_macro_f1_mean:.8f}" for r in variable.loc[variable.rule.eq("intersection")].itertuples()) + "。应分别比较两个K，不能统一断言交集已经包含全部或大部分判别信息。")
    text.append("3. **独有基因的预测价值**：" + "；".join(f"{RULE_LABELS[r.rule]}原K={int(r.k)}的Macro-F1={r.validation_macro_f1_mean:.8f}" for r in variable.loc[variable.rule.isin(["anova_only", "variance_only"])].itertuples()) + "。不同独有集合可有预测能力，但也可能依赖相关的替代信号，不能据此证明新增信息量。")
    for k in (20, 50):
        g = fixed.loc[fixed.k.eq(k)]
        best_single = g.loc[g.rule.isin(["anova", "variance"])].sort_values("validation_macro_f1_mean", ascending=False).iloc[0]
        best_fusion = g.loc[g.rule.str.startswith("fusion")].sort_values("validation_macro_f1_mean", ascending=False).iloc[0]
        comparison = paired.loc[paired.target.eq(best_fusion.scheme) & paired.reference.eq(best_single.scheme)].iloc[0]
        text.append(f"4. **固定预算K={k}**：三个预设融合中平均分较高的{best_fusion.scheme}相对该K较高单方法{best_single.scheme}，折均值差={comparison.delta_macro_f1_mean:+.8f}；同轮OOF更好/更差/相同={int(comparison.n_better_rounds)}/{int(comparison.n_worse_rounds)}/{int(comparison.n_tied_rounds)}。这是描述性概括，不是自动选为最终模型。")
    text.append("5. **逐步补充是否改善**：" + "；".join(f"{r.target}相对ANOVA50折均值差={r.delta_macro_f1_mean:+.8f}" for r in paired.loc[paired.reference.eq("anova_k50") & paired.target.str.startswith("add_variance")].itertuples()) + "。")
    text.append("6. **是否只是数量效应**：" + "；".join(f"{r.target}相对{r.reference}折均值差={r.delta_macro_f1_mean:+.8f}" for r in paired.loc[paired.comparison_design.eq("matched_union_size_each_fold")].itertuples()) + "。只有结合这些同折M匹配结果及60/70/80同预算对照，才能讨论超出增加数量的额外价值。")
    for k in (20, 50):
        st = stability.loc[stability.fixed_budget & stability.k.eq(k)]
        winner = st.sort_values("jaccard_mean", ascending=False).iloc[0]
        single = st.loc[st.rule.isin(["anova", "variance"])].sort_values("jaccard_mean", ascending=False).iloc[0]
        text.append(f"7. **稳定性K={k}**：五种固定预算方案中最高平均Jaccard为{winner.scheme}={winner.jaccard_mean:.6f}；较稳定单方法为{single.scheme}={single.jaccard_mean:.6f}。其他融合的完整值已同时列出，不能由某个融合改善推断所有比例均改善。")
    text += ["8. **性能—数量—稳定性权衡**：同预算性能表、子采样Jaccard表和逐步增加数量对照测量不同属性；例如平均分略高但SD更大、或集合更稳定但分类分数下降，均应作为权衡报告，不用单一指标概括。", "9. **互补还是冗余**：不同独有集合可预测、共同集合可预测、融合可能改善或退化，分别提供不同证据。只有重复出现的同预算/匹配数量预测改善支持特定配置的额外开发集预测价值；这不证明生物学功能互补。接近满分时改善空间受限，与冗余和天花板解释相容；当前实验不足以排除二者并存或确认其机制。"]
    matched_positive = paired.loc[paired.comparison_design.eq("matched_union_size_each_fold") & paired.delta_macro_f1_mean.gt(0)]
    matched_nonpositive = paired.loc[paired.comparison_design.eq("matched_union_size_each_fold") & paired.delta_macro_f1_mean.le(0)]
    text += ["", "### 适用范围内的综合判断", "",
             f"同折并集数量匹配比较中，有{len(matched_positive)}项平均Macro-F1差为正、{len(matched_nonpositive)}项不为正，说明收益依赖原候选K和具体组合，而非普遍的融合优势。不同独有集合仍可预测，与替代或冗余信号相容；部分同数量组合的正向表现则提供有限的预测层面互补证据。现阶段更适合描述为“可替代性与局部融合收益并存”，不将其升级为已证实的生物学功能互补。"]
    text += ["", f"在预定等预算或同折匹配数量对照中，目标减参考平均Macro-F1为正的比较有{len(direct_improvements)}项（完整表同时保留所有负值和并列）。正均值不等于在每轮/每折都改善，也不构成独立显著性或外部验证。", "",
             "**实验直接支持的发现**：上述真实同折成绩、匹配数量对照、患者纠错与退化、集合大小和子采样Jaccard。不同集合各自可预测，只能说明存在多种可用的预测特征子集；融合在等预算/匹配数量下的可重复改善，才为特定方案的额外开发集预测价值提供更直接证据。",
             "",
             "**合理但尚未验证的解释**：如果不同集合均表现良好而融合改善有限，与相关基因信息冗余及接近满分的天花板效应相容；如融合在部分预算改善，同时在另一预算退化，说明替换或加入特征也可能改变间隔和正则化作用。当前实验没有直接测量基因功能互补或建立因果机制，不能在冗余与互补之间作排他判断。",
             "",
             "**方法学限制**：重复CV的100折/20轮相关，子采样435对Jaccard也相关，未做普通独立样本检验或常规独立观测置信区间。多方案探索存在选择乐观偏差；不能自动把均值最高方案当作最终模型或无偏泛化估计。可变集合大小会影响预测和Jaccard，固定预算结果应单独阅读。未做外部队列、批次迁移或临床验证；匿名gene_x不可称为致癌基因或诊断标志物。早期全数据描述探索曾接触801样本，本轮拟合与本轮报告均严格限于640开发样本，最终论文应披露历史探索。",
             "",
             "**对原论文RQ1/RQ2/RQ3的补充**：RQ1增加固定数量替换、逐步加入及并集匹配数量对照；RQ2检验融合选择集合对相同子采样扰动的敏感性；RQ3将预测性能、实际数量和集合稳定性分开衡量。本次不修改此前正式结果，不自动选择最终方案，保留测试集继续隔离。"]
    notes = run / "logs" / "resolved_startup_issues.json"
    if notes.exists():
        text += ["", "## 启动异常与恢复", "", str(read_json(notes)), "", "以上问题已修复，未通过更换基因规则、模型参数或数据划分规避。已完成首折和历史复用断点均保留；实际失败分类折数量由完整记录核验。"]
    (run / "fusion_experiment_report.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    short = ["# 课程论文可用的简洁结论", "",
             "本研究在固定640个开发样本和共享5折×20轮交叉验证下，比较了31个预先设定的单方法、融合、交集/并集及数量匹配方案。161个保留测试样本未参与本轮实验。", ""]
    for k in (20, 50):
        g = fixed.loc[fixed.k.eq(k)]
        single = g.loc[g.rule.isin(["anova", "variance"])].sort_values("validation_macro_f1_mean", ascending=False).iloc[0]
        fusion = g.loc[g.rule.str.startswith("fusion")].sort_values("validation_macro_f1_mean", ascending=False).iloc[0]
        short.append(f"K={k}时，单方法中较高的平均Macro-F1为{single.scheme}={single.validation_macro_f1_mean:.8f}；三种预设融合中较高者为{fusion.scheme}={fusion.validation_macro_f1_mean:.8f}。这些开发集描述值不证明普遍优越性。")
    short += ["", "并集和逐步补充的价值需结合每折相同实际数量的对照解释。完整结果同时报告有利和不利差值、20轮OOF的改善/退化次数，以及具体患者由错误转正确和由正确转错误的记录。",
              "", "融合比例与特征预算影响预测表现和集合稳定性的方式不同。部分方案在同数量对照下存在小幅正向表现，而固定预算融合并非普遍优于单方法；不同独有集合仍具有分类能力。这与特征可替代性、冗余及局部预测互补并存的解释相容，但不能证明基因的因果作用或生物学功能互补。",
              "", "全部交叉验证分数与子采样Jaccard配对相互相关，仅做描述性分析，未进行普通独立样本显著性检验。本轮不自动选择最终模型，也不把探索性均值视为无偏外部泛化能力。"]
    (run / "论文结论摘要.md").write_text("\n".join(short) + "\n", encoding="utf-8")
    return experiment


def write_index(run):
    """结果入口使用相对链接，移动整个项目后仍可阅读。"""
    summary = read_json(run / "fusion_experiment_summary.json")
    lines = ["# 特征互补性与融合消融实验结果索引", "",
             "范围：固定640开发样本，161保留测试样本未参与本轮。31方案×100个相同CV划分，20轮OOF；稳定性使用原30组分层子采样。", "",
             f"真实分类记录：新增{summary['n_new_classifier_fits']}次拟合、复用{summary['n_prior_fits_reused']}次；空集合跳过{summary['n_empty']}折。", "",
             "- [完整中文研究报告](fusion_experiment_report.md)", "- [完整JSON汇总](fusion_experiment_summary.json)",
             "- [论文结论摘要](论文结论摘要.md)",
             "- [固定/可变数量及逐轮OOF性能汇总](fusion_cv_summary.csv)", "- [同折配对性能与患者纠错汇总](fusion_paired_summary.csv)",
             "- [数值与范围验收](verification.json)", "- [项目运行说明](../../../README.md)", "",
             "## 七类PNG（330 DPI）和PDF", ""]
    for picture in sorted((run / "figures").glob("*.png")):
        lines.append(f"- [{picture.name}](figures/{picture.name}) · [PDF](figures/{picture.with_suffix('.pdf').name})")
    lines += ["", "## 完整CSV记录", ""]
    for csv in sorted(run.glob("*.csv")):
        lines.append(f"- [{csv.name}]({csv.name})")
    lines += ["", "## 稳定性与复现原始记录", "",
              "- [复用的30组子采样索引](stability/subsample_indices.csv)", "- [各方案实际入选集合](stability/selected_features_by_subsample.csv)",
              "- [全部435对Jaccard](stability/pairwise_jaccard.csv)", "- [同子采样与单方法重合](stability/overlap_with_single_methods.csv)",
              "- [CV训练/验证样本ID](cv_fold_indices.json)", "- [预先冻结的融合规则](logs/frozen_experiment.json)",
              "- [历史复用核验](logs/reuse_audit.json)", "- [实际环境版本](logs/environment.json)", "- [完整进度日志](logs/progress.log)",
              "- [已解决的启动异常](logs/resolved_startup_issues.json)", "",
              "每折完整训练/验证预测、特征和审计保存在checkpoints/*.npz及JSON中；评分范围在scores_cv和scores_subsamples内按数值/标签摘要绑定。", "",
              "## 恢复运行", "", "在项目根目录执行：", "", "```powershell",
              f'python feature_fusion.py --resume "results/feature_fusion/{run.name}" --n-jobs 1', "```", "",
              "只重做图文和验收：", "", "```powershell",
              f'python feature_fusion.py --resume "results/feature_fusion/{run.name}" --phase report', "```", "",
              "不自动选择最终模型。折分数和Jaccard成对值相关，仅作描述，不是独立外部泛化评估。"]
    (run / "实验结果索引.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
