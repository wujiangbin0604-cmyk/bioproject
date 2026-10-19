# -*- coding: utf-8 -*-
"""对动态仲裁外层重复CV结果作独立的完整性、隔离和指标复核。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score

from ablation_engine import atomic_json, load_checkpoint, read_json
from config import CLASS_ORDER, ExperimentConfig
from cross_validation import make_cv
from data_loader import load_existing_development_data
from dynamic_arbitration import (PATTERNS, SCHEMES, apply_rules, learn_rules,
                                 mode_pattern, verify_source_oof, verify_matched_budget_control)


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def verify_run(run: Path) -> dict:
    run = Path(run)
    cfg = ExperimentConfig(cv_mode="repeated")
    _check(read_json(run/"status.json")["status"] in ("running_nested_cv", "preflight", "failed", "complete"),
           "运行状态文件缺失或状态异常")
    data = load_existing_development_data(cfg, run, strict_rows_only=True)
    Xids = data.X.index.to_numpy(dtype=str)
    y = data.y
    record = read_json(run/"development_data_record.json")
    _check(record["strict_development_rows_only_parsed"] is True and
           record["reserved_values_analyzed"] is False and record["reserved_labels_analyzed"] is False,
           "开发集只读记录显示测试集值/标签被解析")
    _check(len(Xids)==640 and len(data.reserved_test_ids)==161 and not set(Xids)&set(data.reserved_test_ids),
           "固定开发/保留ID数量或隔离失败")
    _check(list(Xids)==read_json(cfg.split_manifest_path)["development_ids"], "开发样本顺序偏离固定划分")
    frozen=read_json(run/"logs/frozen_experiment.json")
    _check(frozen["no_test_set_access"] is True and frozen["outer_cv"]==
           {"splitter":"RepeatedStratifiedKFold","n_splits":5,"n_repeats":20,"random_state":42},
           "冻结配置中的测试隔离或CV参数错误")
    stored_fold_file=read_json(run/"cv_fold_indices.json")["folds"]
    fold_file=[{"evaluation_id":d["evaluation_id"],"repeat":d["repeat_id"],"fold":d["fold_id"],
        "train_sample_ids":d["train_ids"],"validation_sample_ids":d["valid_ids"]} for d in stored_fold_file]
    expected=[]
    for e,(tr,va) in enumerate(make_cv(cfg).split(data.X,data.y),1):
        expected.append({"evaluation_id":e,"repeat":(e-1)//5+1,"fold":(e-1)%5+1,
            "train_sample_ids":Xids[tr].tolist(),"validation_sample_ids":Xids[va].tolist()})
    _check(fold_file==expected and len(fold_file)==100,"外层100折ID索引与固定RepeatedStratifiedKFold不一致")
    source=Path(read_json(run/"logs/preflight.json")["source_run"])
    source_frame,source_frozen,source_audit,source_sha=verify_source_oof(source,data,cfg)
    source_union,source_budget,budget_audit=verify_matched_budget_control(source,data,[
        {"evaluation_id":x["evaluation_id"],"repeat_id":x["repeat"],"fold_id":x["fold"]} for x in fold_file])
    _check(source_sha==frozen["source_oof_sha256"],"历史OOF来源SHA不符")
    source_by_fold={int(e):g.set_index("sample_id")[[f"pred_{m}" for m in "ABC"]]
                    for e,g in source_frame.groupby("evaluation_id",sort=False)}

    inner=pd.read_csv(run/"arbitration/inner_oof_predictions.csv",keep_default_na=False)
    outer=pd.read_csv(run/"evaluation/arbitration_oof_predictions.csv",keep_default_na=False)
    rules_table=pd.read_csv(run/"arbitration/learned_rules_by_outer_fold.csv")
    triggers=pd.read_csv(run/"arbitration/arbitration_trigger_details.csv",keep_default_na=False)
    fit_audit=pd.read_csv(run/"logs/arbitration_fit_audit.csv")
    budget_actual=pd.read_csv(run/"logs/matched_gene_budget_actual_audit.csv")
    folds=pd.read_csv(run/"evaluation/arbitration_fold_results.csv")
    rounds=pd.read_csv(run/"evaluation/arbitration_round_results.csv")
    perclass=pd.read_csv(run/"evaluation/arbitration_per_class_metrics.csv")
    _check(len(inner)==100*512 and len(outer)==100*128 and len(fit_audit)==1800,
           "内层OOF/外层OOF/模型拟合审计记录数量不符")
    _check(not outer.duplicated(["evaluation_id","sample_id"]).any(),"外层OOF出现重复样本×折记录")
    _check(not inner.duplicated(["outer_evaluation_id","sample_id"]).any(),"内层OOF出现重复训练患者")
    _check(len(rounds)==7*20 and len(folds)==7*100 and len(budget_actual)==100,"方案、轮次或折统计记录不完整")
    _check(fit_audit.train_validation_overlap.eq(0).all() and fit_audit.reserved_test_overlap.eq(0).all(),
           "某次Pipeline拟合训练/验证或保留测试ID有交集")
    _check(fit_audit.selector_fit_calls.eq(1).all() and fit_audit.scaler_fit_calls.eq(1).all() and
           fit_audit.classifier_fit_calls.eq(1).all() and fit_audit.selector_fit_samples.eq(fit_audit.n_training).all() and
           fit_audit.scaler_training_samples.eq(fit_audit.n_training).all() and
           fit_audit.scaler_fit_audit_passed.eq(True).all() and fit_audit.selector_input_matches_training.eq(True).all(),
           "选择器/标准化器拟合范围或拟合次数审计失败")
    _check(budget_actual.exact_gene_set_match.eq(True).all() and
           budget_actual.n_actual_unique_genes.eq(budget_actual.n_source_union_genes).all(),
           "三模型实际基因并集与历史同折特征预算不匹配")

    learned_rules={}
    source_lookup={int(r.evaluation_id):set(json.loads(r.union_genes)) for r in source_union.itertuples()}
    trigger_groups={}
    for key,g in triggers.groupby(["evaluation_id","scheme"],sort=False):
        trigger_groups[key]=g.reset_index(drop=True)
    outer_groups={int(e):g.set_index("sample_id") for e,g in outer.groupby("evaluation_id",sort=False)}
    inner_groups={int(e):g.set_index("sample_id") for e,g in inner.groupby("outer_evaluation_id",sort=False)}
    checks_fold=0
    for d in fold_file:
        e=int(d["evaluation_id"]); train_ids=d["train_sample_ids"]; valid_ids=d["validation_sample_ids"]
        train_set,valid_set=set(train_ids),set(valid_ids)
        _check(len(train_set)==512 and len(valid_set)==128 and not train_set&valid_set and
               not (train_set|valid_set)&set(data.reserved_test_ids),f"fold {e} 样本隔离失败")
        inn=inner_groups[e]
        _check(set(inn.index)==train_set and len(inn)==512 and
               inn["y_true"].to_dict()==y.loc[train_ids].to_dict(),f"fold {e} 内层患者/标签不匹配")
        _check(inn.groupby("sample_id").size().eq(1).all(),f"fold {e} 内层OOF患者不唯一")
        rules,stats=learn_rules(inn.reset_index(),train_ids,valid_ids)
        meta,a=load_checkpoint(run/f"checkpoints/outer_{e:03d}",frozen["identity"])
        _check(meta["outer_validation_labels_used_for_rule"] is False and meta["rule_locked_before_outer_fit"] is True,
               f"fold {e} 仲裁规则锁定记录异常")
        _check(rules==meta["rules"],f"fold {e} 学习规则无法由内部OOF复现")
        learned_rules[e]=rules
        out=outer_groups[e].loc[valid_ids]
        _check(len(out)==128 and out.y_true.tolist()==y.loc[valid_ids].tolist(),f"fold {e} 外层OOF标签/ID顺序错位")
        base=out[["pred_A","pred_B","pred_C"]].to_numpy(dtype=str)
        _check(np.array_equal(base,a["outer_predictions"].astype(str)),f"fold {e} OOF预测与模型断点不符")
        _check(np.array_equal(base,source_by_fold[e].loc[valid_ids].to_numpy(dtype=str)),f"fold {e} 与历史同折模型预测不一致")
        patterns=mode_pattern(base)
        _check(np.array_equal(patterns,out.pattern.to_numpy(dtype=str)),f"fold {e} 分歧模式标签错误")
        routed,td=apply_rules(base,patterns,rules)
        _check(np.array_equal(routed["hard_vote"],out.pred_hard_vote.to_numpy(dtype=str)),f"fold {e} 硬投票规则错误")
        for scheme in SCHEMES:
            col={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
                "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
                "conservative_fallback":"pred_conservative_fallback"}[scheme]
            _check(np.array_equal(routed[scheme],out[col].to_numpy(dtype=str)),f"fold {e} {scheme}路由结果不符")
            tr=trigger_groups[(e,scheme)]
            _check(tr.sample_id.tolist()==valid_ids and tr.triggered.astype(str).str.lower().isin(["true","false"]).all(),
                   f"fold {e} {scheme}触发记录顺序或值异常")
            _check(tr.triggered.astype(str).str.lower().map({"true":True,"false":False}).tolist()==td.loc[td.scheme.eq(scheme),"triggered"].tolist(),
                   f"fold {e} {scheme}触发标记不符")
        selected=np.asarray(a["selected"])
        _check(selected.shape==(3,50) and all(len(set(row.tolist()))==50 for row in selected),f"fold {e} Top50特征数量异常")
        genes=set(data.X.columns[np.unique(selected)].astype(str))
        _check(genes==source_lookup[e],f"fold {e} 外层真实选择特征并集与历史并集不符")
        checks_fold+=1

    _check(len(trigger_groups)==100*len(SCHEMES),"触发明细缺少方法/折组合")
    _check(outer.groupby("sample_id").size().eq(20).all() and outer.sample_id.nunique()==640,
           "每个开发患者没有恰好20次外层预测")
    _check(set(outer.y_true).issubset(CLASS_ORDER) and all(set(outer[c]).issubset(CLASS_ORDER)
           for c in ["pred_A","pred_B","pred_C","pred_hard_vote","pred_fixed_disagreement","pred_learned_inner_oof","pred_conservative_fallback"]),
           "OOF出现未知癌种类别")
    metric_checks=0
    for row in folds.itertuples():
        g=outer.loc[outer.evaluation_id.eq(row.evaluation_id)].set_index("sample_id").loc[fold_file[int(row.evaluation_id)-1]["validation_sample_ids"]]
        col={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
             "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
             "conservative_fallback":"pred_conservative_fallback"}[row.scheme]
        truth=g.y_true.to_numpy();pred=g[col].to_numpy()
        np.testing.assert_allclose(row.macro_f1,f1_score(truth,pred,labels=list(CLASS_ORDER),average="macro",zero_division=0),atol=1e-12)
        np.testing.assert_allclose(row.balanced_accuracy,balanced_accuracy_score(truth,pred),atol=1e-12)
        np.testing.assert_allclose(row.accuracy,accuracy_score(truth,pred),atol=1e-12)
        metric_checks+=1
    for r in range(1,21):
        g=outer.loc[outer.repeat_id.eq(r)]
        _check(len(g)==640 and g.sample_id.nunique()==640 and set(g.sample_id)==set(Xids),f"第{r}轮OOF覆盖错误")
    _check((run/"arbitration/arbitration_rule_definitions.json").is_file(),"冻结仲裁规则定义文件缺失")
    result={"status":"passed","checks_passed":23+checks_fold+metric_checks,"n_development_samples":640,
        "n_reserved_test_ids_in_fixed_manifest":161,"reserved_expression_or_labels_parsed":False,
        "outer_folds_verified":checks_fold,"inner_oof_events_verified":len(inner),"outer_oof_events_verified":len(outer),
        "pipeline_fit_audits_verified":len(fit_audit),"fold_scheme_metric_rows_recomputed":metric_checks,
        "historical_source_oof_sha256":source_sha,"same_split_union_budget_rows_verified":len(budget_audit),
        "same_outer_fold_base_predictions_reproduced":True,"top50_union_matches_historical_control_all_folds":True,
        "rules_recomputed_only_from_inner_oof":True,"outer_validation_labels_used_for_rules":False,
        "all_three_pipeline_steps_fit_inside_the_correct_training_fold":True,
        "no_independent_sample_significance_test":True}
    atomic_json(run/"verification.json",result)
    return result


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory",type=Path)
    args=parser.parse_args()
    print(json.dumps(verify_run(args.run_directory),ensure_ascii=False,indent=2))
