# -*- coding: utf-8 -*-
"""三模型分歧分析、训练折内OOF仲裁学习和隔离的外层重复交叉验证。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import time
import traceback

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from ablation_engine import (atomic_json, build_pipeline, fit_classification_task, load_checkpoint, read_json,
                             save_checkpoint, sha256)
from config import CLASS_ORDER, PROJECT_DIR, ExperimentConfig
from cross_validation import frozen_pipeline_record, make_cv
from data_loader import load_existing_development_data
from fusion_selection import prepare_scores, training_digest
from hard_voting import BASE_MODELS, fast_scores, latest, vote_labels

SCHEMES = ("model_A", "model_B", "model_C", "hard_vote", "fixed_disagreement",
           "learned_inner_oof", "conservative_fallback")
SCHEME_LABELS = {"model_A": "A：ANOVA+SVM", "model_B": "B：高方差+SVM", "model_C": "C：ANOVA+LR",
                 "hard_vote": "等权硬投票", "fixed_disagreement": "固定分歧规则（探索性）",
                 "learned_inner_oof": "训练集内部学习", "conservative_fallback": "分歧触发+回退A"}
PATTERNS = ("P0", "P1", "P2", "P3", "P4")
PATTERN_DEFINITIONS = {"P0": "A=B=C", "P1": "A=B≠C", "P2": "A=C≠B", "P3": "B=C≠A", "P4": "A、B、C全部不同"}
FIXED_RULE = {"P0": "A", "P1": "A", "P2": "B", "P3": "A", "P4": "A"}
DEFAULT_MODEL = "A"
MIN_UNIQUE_PATIENTS = 10
MIN_NET_CORRECTIONS = 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mode_pattern(predictions):
    """按三模型输出类别，确定性分类P0至P4。"""
    p = np.asarray(predictions, dtype=str)
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError("预测数组必须为 n×3")
    a, b, c = p.T
    result = np.full(len(p), "P4", dtype="U2")
    same_ab, same_ac, same_bc = a == b, a == c, b == c
    result[same_ab & same_ac] = "P0"
    result[same_ab & ~same_ac] = "P1"
    result[same_ac & ~same_ab] = "P2"
    result[same_bc & ~same_ab] = "P3"
    return result


def _accuracy_gain(y_true, default, candidate):
    corrected = int(np.sum((default != y_true) & (candidate == y_true)))
    added = int(np.sum((default == y_true) & (candidate != y_true)))
    return {"corrected": corrected, "new_errors": added, "net_gain": corrected - added}


def learn_rules(inner_oof: pd.DataFrame, outer_train_ids, outer_validation_ids):
    """每个患者恰有一次内层OOF；只看外层训练集的内部OOF标签学习规则。"""
    train_set, validation_set = set(outer_train_ids), set(outer_validation_ids)
    ids = inner_oof.sample_id.tolist()
    require(len(ids) == len(set(ids)) == len(train_set) and set(ids) == train_set,
            "仲裁学习要求每名外层训练患者恰好有一次内部OOF预测")
    require(not set(ids) & validation_set, "外层验证样本进入仲裁学习")
    require(set(inner_oof.y_true.unique()).issubset(set(CLASS_ORDER)), "内部OOF含未知类别")
    require(inner_oof.groupby("sample_id").y_true.nunique().eq(1).all(), "内部OOF同一患者真实标签不一致")
    learned, stats = {}, []
    for pattern in PATTERNS:
        subset = inner_oof.loc[inner_oof.pattern.eq(pattern)]
        n = int(subset.sample_id.nunique())
        base = subset.correct_A.to_numpy(dtype=bool)
        candidate_details = {"A": {"corrected": 0, "new_errors": 0, "net_gain": 0}}
        for member in ("B", "C"):
            candidate_details[member] = _accuracy_gain(subset.y_true.to_numpy(),
                subset.pred_A.to_numpy(), subset[f"pred_{member}"].to_numpy())
        # 固定优先级B再C，仅处理净收益并列；不是看外层验证成绩选优。
        winner = "A"
        best_gain = 0
        for member in ("B", "C"):
            gain = candidate_details[member]["net_gain"]
            if gain > best_gain:
                winner, best_gain = member, gain
        enough_n = n >= MIN_UNIQUE_PATIENTS
        eligible = enough_n and best_gain >= MIN_NET_CORRECTIONS and winner != "A"
        selected = winner if eligible else "A"
        learned[pattern] = selected
        reason = ("thresholds_met" if eligible else "fewer_than_10_unique_training_patients" if not enough_n
                  else "no_candidate_net_gain_of_at_least_2")
        row = {"pattern": pattern, "pattern_definition": PATTERN_DEFINITIONS[pattern],
               "n_inner_oof_events": len(subset), "n_unique_training_patients": n,
               "default_model_A_correct": int(subset.correct_A.sum()),
               "model_A_correct": int(subset.correct_A.sum()), "model_B_correct": int(subset.correct_B.sum()),
               "model_C_correct": int(subset.correct_C.sum()), "candidate_B_corrected": candidate_details["B"]["corrected"],
               "candidate_B_new_errors": candidate_details["B"]["new_errors"],
               "candidate_B_net_gain": candidate_details["B"]["net_gain"],
               "candidate_C_corrected": candidate_details["C"]["corrected"],
               "candidate_C_new_errors": candidate_details["C"]["new_errors"],
               "candidate_C_net_gain": candidate_details["C"]["net_gain"],
               "minimum_unique_patient_threshold": MIN_UNIQUE_PATIENTS,
               "minimum_net_correction_threshold": MIN_NET_CORRECTIONS,
               "sample_threshold_met": enough_n, "net_gain_threshold_met": best_gain >= MIN_NET_CORRECTIONS,
               "best_candidate_before_threshold": winner, "best_candidate_net_gain": best_gain,
               "selected_model": selected, "eligible_to_override_A": eligible, "fallback_reason": reason,
               "rule_training_ids_only": True, "outer_validation_ids_used_for_rule": False,
               "inner_oof_y_true_only": True}
        stats.append(row)
    return learned, stats


def apply_rules(predictions, patterns, learned_rules):
    """不接收真值的路由函数；按已经锁定的pattern表输出模型标签和仲裁来源。"""
    p = np.asarray(predictions, dtype=str)
    modes = np.asarray(patterns, dtype=str)
    if p.shape != (len(modes), 3):
        raise ValueError("仲裁预测/模式维度不一致")
    learned_model = np.array([learned_rules[x] for x in modes], dtype="U1")
    fixed_model = np.array([FIXED_RULE[x] for x in modes], dtype="U1")
    conservative_model = learned_model.copy()
    # 一致预测无须仲裁；其余无合格内部规则的模式回退到A。
    index = {"A": 0, "B": 1, "C": 2}
    pred = {"model_A": p[:, 0], "model_B": p[:, 1], "model_C": p[:, 2]}
    pred["hard_vote"] = vote_labels(p)[0]
    pred["fixed_disagreement"] = np.array([p[i, index[m]] for i, m in enumerate(fixed_model)])
    pred["learned_inner_oof"] = np.array([p[i, index[m]] for i, m in enumerate(learned_model)])
    pred["conservative_fallback"] = np.array([p[i, index[m]] for i, m in enumerate(conservative_model)])
    rows = []
    for i, pattern in enumerate(modes):
        discordant = pattern != "P0"
        for scheme in SCHEMES:
            if scheme in ("model_A", "model_B", "model_C", "hard_vote"):
                trigger, member = False, scheme[-1] if scheme.startswith("model_") else "majority"
                reason = "baseline_no_arbitration"
            elif scheme == "fixed_disagreement":
                trigger, member = discordant, fixed_model[i]
                reason = "predeclared_exploratory_pattern_rule" if trigger else "three_models_agree"
            elif scheme == "learned_inner_oof":
                member = learned_model[i]
                trigger = discordant and member != "A"
                reason = "inner_OOF_thresholds_met" if trigger else "learned_rule_defaults_to_A" if discordant else "three_models_agree"
            else:
                member = conservative_model[i]
                trigger = discordant and member != "A"
                reason = "eligible_disagreement_arbitrated" if trigger else "fallback_to_A_insufficient_evidence" if discordant else "three_models_agree"
            rows.append({"scheme": scheme, "pattern": pattern, "triggered": bool(trigger),
                         "selected_member": member, "trigger_reason": reason,
                         "predicted_class": pred[scheme][i], "tie_rule_applied": bool(pattern == "P4" and scheme == "hard_vote")})
    return pred, pd.DataFrame(rows)


def latest_run(pointer):
    return PROJECT_DIR / "results" / read_json(PROJECT_DIR / "results" / pointer)["run_directory"]


def log(run, message):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    p = run / "logs/run.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _save_csv(frame, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _row_for_mode(mode):
    a, b, c = mode
    if a == b == c: return "P0"
    if a == b: return "P1"
    if a == c: return "P2"
    if b == c: return "P3"
    return "P4"


def verify_source_oof(source, data, cfg):
    """逐一对照哈希校验的每折断点及原始OOf CSV，确认样本顺序和预测来源。"""
    frozen = read_json(source / "logs/frozen_experiment.json")
    require(read_json(source / "status.json")["status"] == "complete", "现有硬投票运行没有完成")
    for key, method in (("anova_svm_k50", "anova_svm"), ("variance_svm_k50", "variance_svm"),
                        ("anova_lr_k50", "anova_lr")):
        current = frozen_pipeline_record(build_pipeline(cfg, method, 50), method,
                                          "variance" if method == "variance_svm" else "anova", 50)
        require(frozen["pipelines"][key] == current, f"基础模型的现有参数配置不一致：{key}")
    folds = read_json(source / "cv_fold_indices.json")
    expected = {"cv_mode": "repeated", "folds": []}
    ids = data.X.index.to_numpy()
    for e, (tr, va) in enumerate(make_cv(cfg).split(data.X, data.y), 1):
        expected["folds"].append({"evaluation_id": e, "repeat": (e - 1) // 5 + 1, "fold": (e - 1) % 5 + 1,
                                   "train_sample_ids": ids[tr].tolist(), "validation_sample_ids": ids[va].tolist()})
    require(folds == expected, "原硬投票CV索引/样本顺序不等于本次固定索引")
    require(frozen["development_fingerprint"] == read_json(data.split_manifest_path)["dataset_fingerprint_sha256"] or
            frozen["development_fingerprint"] == read_json(source / "development_data_record.json")["development_fingerprint_sha256"],
            "源开发集指纹缺少对应记录")
    oof_path = source / "ensemble_oof_predictions.csv"
    frame = pd.read_csv(oof_path)
    require(len(frame) == 12800 and not frame.duplicated(["evaluation_id", "sample_id"]).any(), "原OOF记录缺失或重复")
    require(set(frame.sample_id) == set(data.X.index) and frame.groupby("sample_id").size().eq(20).all(), "OOF患者覆盖/重复预测次数不符")
    require(frame.groupby("sample_id").y_true.nunique().eq(1).all(), "患者真实标签跨轮不同")
    require(set(frame.y_true).issubset(CLASS_ORDER) and all(set(frame[f"pred_{m}"]).issubset(CLASS_ORDER) for m in "ABC"), "OOF类别编码不符")
    frame["pattern"] = mode_pattern(frame[[f"pred_{m}" for m in "ABC"]].to_numpy())
    for model in "ABC":
        require(frame[f"correct_{model}"].eq(frame[f"pred_{model}"].eq(frame.y_true)).all(), f"原OOF {model}正确标记不符")
    vote, vflags = vote_labels(frame[[f"pred_{m}" for m in "ABC"]].to_numpy())
    require(np.array_equal(vote, frame.pred_vote.to_numpy()), "历史硬投票结果和预设规则不符")
    require(frame.all_three_different.eq(vflags["all_three_different"]).all(), "历史全异标记不符")
    id_index = {sid: i for i, sid in enumerate(data.X.index)}
    id_check = []
    for d in folds["folds"]:
        e, va = d["evaluation_id"], d["validation_sample_ids"]
        require(len(va) == len(set(va)) == 128 and not set(d["train_sample_ids"]) & set(va), "源折训练/验证样本重叠")
        require(not (set(va) | set(d["train_sample_ids"])) & set(data.reserved_test_ids), "保留ID出现在源折")
        meta, arrays = load_checkpoint(source / f"checkpoints/fold_{e:03d}", frozen["identity"])
        part = frame.loc[frame.evaluation_id.eq(e)].set_index("sample_id").loc[va]
        require(part.repeat_id.eq(d["repeat"]).all() and part.fold_id.eq(d["fold"]).all(), "OOF轮次/折号不匹配")
        require(part.y_true.tolist() == data.y.loc[va].tolist(), "OOF标签与样本ID错位")
        require(np.array_equal(part[[f"pred_{m}" for m in "ABC"]].to_numpy(), arrays["valid_predictions"]), "OOF与折断点预测不一致")
        require(np.array_equal(arrays["valid_vote"], part.pred_vote.to_numpy()), "OOF与硬投票断点不一致")
        audit = meta["audits"]
        require(len(audit) == 3 and {a.get("model") for a in audit} == {"A","B","C"} and
                all(a["train_validation_overlap"] == 0 and a["reserved_test_overlap"] == 0 for a in audit),
                "历史拟合审计不完整")
        id_check.append({"evaluation_id": e, "n_training_ids": len(d["train_sample_ids"]), "n_validation_ids": len(va),
                         "all_base_predictions_match_checkpoint": True, "labels_aligned": True, "reserved_test_id_count": 0,
                         "source_checkpoint_sha256": sha256(source / f"checkpoints/fold_{e:03d}.npz")})
    return frame, frozen, id_check, sha256(oof_path)


def verify_matched_budget_control(source, data, fold_defs):
    """核验历史并集单模型的特征预算逐折与本轮三个外层模型严格一致。"""
    features_path = source / "ensemble_feature_union.csv"
    results_path = source / "ensemble_matched_budget_fold_results.csv"
    require(features_path.is_file() and results_path.is_file(), "缺少历史同折并集基因预算对照记录")
    features = pd.read_csv(features_path)
    results = pd.read_csv(results_path)
    features = features.sort_values("evaluation_id").reset_index(drop=True)
    control = results.loc[results.scheme.eq("union_k50")].sort_values("evaluation_id").reset_index(drop=True)
    require(len(features) == len(fold_defs) == 100 and len(control) == 100,
            "并集基因或同预算模型的100折记录不完整")
    require(features.evaluation_id.tolist() == [x["evaluation_id"] for x in fold_defs],
            "并集基因列表 evaluation_id 顺序错误")
    require(control.evaluation_id.tolist() == [x["evaluation_id"] for x in fold_defs],
            "并集基因预算分类器 evaluation_id 顺序错误")
    feature_audit = []
    for expected, feature_row, model_row in zip(fold_defs, features.itertuples(), control.itertuples()):
        e = expected["evaluation_id"]
        require((feature_row.repeat_id, feature_row.fold_id) == (expected["repeat_id"], expected["fold_id"]),
                f"历史并集基因CV轮次不匹配：fold {e}")
        require((model_row.repeat_id, model_row.fold_id) == (expected["repeat_id"], expected["fold_id"]),
                f"历史并集SVM CV轮次不匹配：fold {e}")
        union = json.loads(feature_row.union_genes)
        require(len(union) == len(set(union)) == int(feature_row.n_distinct_genes_system),
                f"历史并集基因列表重复/数量不符：fold {e}")
        require(set(union).issubset(set(data.X.columns)), f"历史并集包含非原始表达特征：fold {e}")
        require(int(model_row.n_features) == len(union), f"历史同预算SVM维度不匹配：fold {e}")
        feature_audit.append({"evaluation_id":e,"repeat_id":expected["repeat_id"],"fold_id":expected["fold_id"],
            "n_features":len(union),"feature_union_matches_saved_budget_model":True,
            "fold_ids_match_current_cv":True,"source_union_row_sha256":sha256(features_path),
            "source_budget_result_sha256":sha256(results_path)})
    return features, control, feature_audit


def historical_analysis(frame):
    rows, patient_rows = [], []
    df = frame.copy()
    df["correct_H"] = df.correct_vote
    df["correct_count"] = df[[f"correct_{m}" for m in "ABC"]].sum(axis=1)
    df["all_three_wrong"] = df.correct_count.eq(0)
    df["only_one_correct"] = df.correct_count.eq(1)
    df["disagreement"] = df.pattern.ne("P0")
    df["fixed_member"] = df.pattern.map(FIXED_RULE)
    model_index = {m:i for i,m in enumerate("ABC")}
    pred = df[[f"pred_{m}" for m in "ABC"]].to_numpy()
    df["pred_fixed"] = [pred[i, model_index[m]] for i,m in enumerate(df.fixed_member)]
    df["correct_fixed"] = df.pred_fixed.eq(df.y_true)
    for pattern in PATTERNS:
        g = df.loc[df.pattern.eq(pattern)]
        unique = g.sample_id.nunique()
        rows.append({"pattern": pattern, "definition": PATTERN_DEFINITIONS[pattern], "prediction_events": len(g),
            "unique_patients": unique, "event_proportion": len(g)/len(df) if len(df) else 0,
            "patients_proportion_of_all_640": unique/len(df.sample_id.unique()) if len(df) else 0,
            "n_BRCA_events": int(g.y_true.eq("BRCA").sum()), "n_COAD_events": int(g.y_true.eq("COAD").sum()),
            "n_KIRC_events": int(g.y_true.eq("KIRC").sum()), "n_LUAD_events": int(g.y_true.eq("LUAD").sum()),
            "n_PRAD_events": int(g.y_true.eq("PRAD").sum()),
            "n_correct_A": int(g.correct_A.sum()), "n_correct_B": int(g.correct_B.sum()), "n_correct_C": int(g.correct_C.sum()),
            "n_correct_hard_vote": int(g.correct_vote.sum()), "n_correct_fixed_historical_only": int(g.correct_fixed.sum()),
            "accuracy_A": float(g.correct_A.mean()) if len(g) else None,
            "accuracy_B": float(g.correct_B.mean()) if len(g) else None,
            "accuracy_C": float(g.correct_C.mean()) if len(g) else None,
            "accuracy_hard_vote": float(g.correct_vote.mean()) if len(g) else None,
            "accuracy_fixed_rule_posthoc_descriptive_only": float(g.correct_fixed.mean()) if len(g) else None,
            "all_three_wrong_events": int(g.all_three_wrong.sum()), "only_one_model_correct_events": int(g.only_one_correct.sum()),
            "distinct_true_cancers": int(g.y_true.nunique())})
    for sid, g in df.groupby("sample_id", sort=False):
        pm = g.pattern.value_counts()
        patient_rows.append({"sample_id": sid, "y_true": g.y_true.iloc[0], "n_oof_events": len(g),
            "disagreement_events": int(g.disagreement.sum()), "disagreement_rate": float(g.disagreement.mean()),
            "n_distinct_patterns": int(g.pattern.nunique()), "pattern_changed_across_repeats": g.pattern.nunique() > 1,
            "P0_events": int(pm.get("P0", 0)), "P1_events": int(pm.get("P1", 0)), "P2_events": int(pm.get("P2", 0)),
            "P3_events": int(pm.get("P3", 0)), "P4_events": int(pm.get("P4", 0)),
            "A_errors": int((~g.correct_A).sum()), "B_errors": int((~g.correct_B).sum()), "C_errors": int((~g.correct_C).sum()),
            "hard_vote_errors": int((~g.correct_vote).sum()), "fixed_rule_errors_historical_only": int((~g.correct_fixed).sum()),
            "all_three_wrong_events": int(g.all_three_wrong.sum()), "only_one_model_correct_events": int(g.only_one_correct.sum()),
            "disagreement_repeats": json.dumps(g.loc[g.disagreement, "repeat_id"].astype(int).tolist())})
    patient = pd.DataFrame(patient_rows)
    patient_disc = patient.loc[patient.disagreement_events.gt(0), "sample_id"]
    detail = df.loc[df.disagreement | df[[f"correct_{m}" for m in "ABC"]].eq(False).any(axis=1)].copy()
    detail["fixed_rule_source_member"] = detail.fixed_member
    detail["fixed_rule_correct_historical_only"] = detail.correct_fixed
    return pd.DataFrame(rows), patient, detail, patient_disc


def write_stage1_report(path, patterns, patients, details):
    from ablation_report import markdown_table
    disc = patterns.loc[patterns.pattern.ne("P0")]
    p2 = patterns.loc[patterns.pattern.eq("P2")].iloc[0]
    p1 = patterns.loc[patterns.pattern.eq("P1")].iloc[0]
    p3 = patterns.loc[patterns.pattern.eq("P3")].iloc[0]
    affected = patients.loc[patients.disagreement_events.gt(0)].sort_values("disagreement_events", ascending=False)
    p2ids = details.loc[details.pattern.eq("P2"), "sample_id"].value_counts()
    p2cancer = details.loc[details.pattern.eq("P2"), "y_true"].value_counts()
    unanimous_wrong = patterns.loc[patterns.pattern.eq("P0"), "all_three_wrong_events"].iloc[0]
    allwrong = details.loc[details.all_three_wrong]
    onlyone = details.loc[details.only_one_correct]
    top_patient = affected.head(8)[["sample_id", "y_true", "disagreement_events", "n_distinct_patterns", "A_errors", "B_errors", "C_errors", "hard_vote_errors"]]
    mode_table = patterns.copy()
    for name in ("accuracy_A", "accuracy_B", "accuracy_C", "accuracy_hard_vote"):
        mode_table[name] = mode_table[name].map(lambda v: "NA" if pd.isna(v) else f"{v:.4f}")
    mode_table["true_class_event_counts_BRCA_COAD_KIRC_LUAD_PRAD"] = mode_table.apply(
        lambda r: ", ".join(str(int(r[f"n_{c}_events"])) for c in CLASS_ORDER), axis=1)
    p2_distribution = pd.DataFrame({"patient_id": p2ids.index, "P2_events": p2ids.values}).merge(
        details.loc[details.pattern.eq("P2")].drop_duplicates("sample_id")[["sample_id", "y_true"]],
        left_on="patient_id", right_on="sample_id", how="left").drop(columns="sample_id")
    content = f'''# 历史OOF预测分歧与错误分析（探索性）

## 数据范围和核验

本分析逐行重新核验此前三模型硬投票运行的12,800条OOF事件，覆盖640名开发集患者，每人20次预测，按原始sample ID关联标签。三模型预测与100个折级NPZ断点逐项一致；Fold/repeat ID、标签类别和各模型正确标记已复核。161名保留样本没有解析表达或标签，也未进入本分析。详见本次运行 `logs/source_oof_audit.csv` 与 `logs/data_leakage_audit.json`。

本节只描述已经查看过的历史开发OOF，属于探索性发现；固定分歧规则由该历史信息启发。它的历史回算准确率不能称为独立验证，也不得用于声称外层验证的无偏性能。

## 分歧模式

| 模式 | A/B/C输出关系 |
|---|---|
| P0 | A=B=C |
| P1 | A=B≠C |
| P2 | A=C≠B |
| P3 | B=C≠A |
| P4 | 三者全部不同 |

| 模式 | 预测事件数 | 独立患者数 | A正确率 | B正确率 | C正确率 | 硬投票正确率 | 各癌种事件数（BRCA、COAD、KIRC、LUAD、PRAD） |
|---|---:|---:|---:|---:|---:|---:|---|
{markdown_table(mode_table[["pattern","prediction_events","unique_patients","accuracy_A","accuracy_B","accuracy_C","accuracy_hard_vote","true_class_event_counts_BRCA_COAD_KIRC_LUAD_PRAD"]])}

P0以外共有{int(disc.prediction_events.sum())}次分歧事件，涉及{int(affected.sample_id.nunique())}名不同患者；占12,800事件的{disc.prediction_events.sum()/12800:.3%}，涉及全部开发患者的{affected.sample_id.nunique()/640:.3%}。三者完全不同的P4为{int(patterns.loc[patterns.pattern.eq('P4'),'prediction_events'].iloc[0])}次。虽然分歧事件重复出现多次，但独立患者数很少，不能把重复轮次当作新增训练样本。

### P2：A=C≠B

P2共有{int(p2.prediction_events)}次事件、{int(p2.unique_patients)}名患者；B正确{int(p2.n_correct_B)}次（{p2.accuracy_B:.2%}），A和C分别正确{int(p2.n_correct_A)}次（{p2.accuracy_A:.2%}）与{int(p2.n_correct_C)}次（{p2.accuracy_C:.2%}）。按患者的事件分布：

{markdown_table(p2_distribution)}

真值癌种事件计数：{json.dumps({str(k):int(v) for k,v in p2cancer.items()},ensure_ascii=False)}。这说明B在该模式下可能修正A/C共同错误，但证据由仅{int(p2.unique_patients)}名开发患者贡献，并且同一患者会跨CV轮次重复出现；该模式正确率不能直接推广到新患者。

### P1、P3及个体集中

P1为{int(p1.prediction_events)}次、{int(p1.unique_patients)}名患者；P3为{int(p3.prediction_events)}次、{int(p3.unique_patients)}名患者。各模型正确率和癌种频数见 `disagreement_pattern_summary.csv`。任一分歧患者跨轮次模式数量见 `disagreement_patient_summary.csv`。错误或分歧最集中的患者（最多8人）如下：

{markdown_table(top_patient)}

三模型共同错误事件有{len(allwrong)}次，涉及{allwrong.sample_id.nunique()}名患者，其中同意预测但错误的P0事件有{int(unanimous_wrong)}次；共同预测不保证正确。恰好只有一个基础模型正确的事件有{len(onlyone)}次。所有分歧事件或任一模型出错事件逐条记录在 `disagreement_error_details.csv`，包括sample ID、轮次、模式、真实类别及四种已知预测结果。

## 对仲裁可行性的判断

1. **分歧与错误。** 在全部重复OOF事件中，分歧模式下单模型错误率与一致模式下不同；这只是已查看开发集内的描述性关系。先按表查看各模式A/B/C正确率，再注意患者重复和选择模式的历史偏差，不能把较高正确率当成外部证据。
2. **患者数。** 分歧虽然有{int(disc.prediction_events.sum())}次事件，却仅涉及{int(affected.sample_id.nunique())}名不同患者，故有效监督证据非常稀少。
3. **错误互补。** P2中B有时能纠正A/C；P1/P3中各模型的正确率和正确事件也不同，说明有局部互补。然而共误判、三者共识错误和分歧中的错误同样存在；规则是否有用必须在每个外层训练集内部重学，再在未参与规则学习的外层折评价。
4. **过拟合风险。** 仅{int(affected.sample_id.nunique())}名历史分歧患者远少于预设最低支持的10人；按患者去重后不能达到阈值。复杂元分类器会严重过拟合。本研究只继续执行预注册的简单查表门槛；若折内模式样本不足就回退A，不调低门槛、不根据外层效果改规则。

固定分歧规则在这批历史OOF上的回算结果已在模式表中标明 `posthoc_descriptive_only`，属于数据启发后再查看的结果，不能称作隔离验证。
'''
    Path(path).write_text(content, encoding="utf-8")


def _history_patient(frame):
    return historical_analysis(frame)[1]


def resource_report(source_frame, folds, data):
    source_fold = pd.read_csv(latest("latest_hard_voting_ensemble.json") / "ensemble_fold_results.csv") if False else None
    # 三模型已有拟合耗时提供实测先验；内部折训练样本约为外层训练集的4/5。
    fit_sum = float(source_frame.attrs.get("historical_fit_seconds", 63.4861402))
    inner_fits, outer_fits = len(folds) * 5 * 3, len(folds) * 3
    mean_inner_train = float(source_frame.attrs.get("mean_inner_train", 409.6))
    predicted_inner = fit_sum * (inner_fits / 300) * mean_inner_train / 512
    predicted_outer = fit_sum
    return {"outer_splits": len(folds), "inner_splits": len(folds) * 5,
            "inner_model_fits": inner_fits, "outer_model_fits": outer_fits,
            "total_model_fits": inner_fits + outer_fits,
            "mean_inner_training_samples_estimated": mean_inner_train,
            "historical_three_models_300_outer_fits_seconds": fit_sum,
            "estimated_inner_fit_seconds": predicted_inner,
            "estimated_outer_fit_seconds": predicted_outer,
            "estimated_total_fit_seconds": predicted_inner + predicted_outer,
            "estimated_end_to_end_minutes_range": [max(1, round((predicted_inner+predicted_outer)*1.35/60,1)),
                                                    round((predicted_inner+predicted_outer)*2.1/60,1)],
            "dev_matrix_float64_megabytes": round(640*20531*8/1024**2,2),
            "parallel_jobs": 1,
            "runtime_note": "估计依据已有同配置折拟合实测时间，并按内层训练样本比例缩放；系统负载和评分缓存IO会改变实际时长。"}


def run(args):
    # 该任务明确复用历史的RepeatedStratifiedKFold 5×20拆分；项目默认配置仍是standard。
    cfg = ExperimentConfig(cv_mode="repeated")
    source = Path(args.source_run).resolve() if args.source_run else latest_run("latest_hard_voting_ensemble.json")
    run_dir = Path(args.resume).resolve() if args.resume else cfg.output_dir / "dynamic_arbitration" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for sub in ("analysis", "arbitration", "evaluation", "figures", "logs", "checkpoints/outer_members", "checkpoints/inner_members", "scores/outer", "scores/inner"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    try:
        atomic_json(run_dir / "status.json", {"status": "preflight", "started": datetime.now().isoformat()})
        log(run_dir, "严格读取当前固定划分的640名开发患者；不解析保留样本表达或标签。")
        data = load_existing_development_data(cfg, run_dir, strict_rows_only=True)
        X = data.X.to_numpy(dtype=np.float64)
        y = data.y.to_numpy(dtype=str)
        ids = data.X.index.to_numpy(dtype=str)
        fold_defs = []
        for evaluation_id, (train, valid) in enumerate(make_cv(cfg).split(data.X, data.y), 1):
            fold_defs.append({"evaluation_id": evaluation_id, "repeat_id": (evaluation_id-1)//5+1,
                              "fold_id": (evaluation_id-1)%5+1, "train_index": train, "valid_index": valid,
                              "train_ids": ids[train].tolist(), "valid_ids": ids[valid].tolist()})
        matrix_bytes = len(X.tobytes())
        source_frame, source_frozen, source_audit, source_oof_sha = verify_source_oof(source, data, cfg)
        budget_features, budget_models, budget_audit = verify_matched_budget_control(source, data, fold_defs)
        matched_union_by_eval = {int(r.evaluation_id): set(json.loads(r.union_genes))
                                 for r in budget_features.itertuples()}
        source_predictions_by_eval = {int(e): g.set_index("sample_id")[[f"pred_{m}" for m in "ABC"]]
                                     for e, g in source_frame.groupby("evaluation_id", sort=False)}
        source_frame["pattern"] = mode_pattern(source_frame[[f"pred_{m}" for m in "ABC"]].to_numpy())
        pattern_summary, patient_summary, error_details, affected = historical_analysis(source_frame)
        _save_csv(pattern_summary, run_dir / "analysis/disagreement_pattern_summary.csv")
        _save_csv(patient_summary, run_dir / "analysis/disagreement_patient_summary.csv")
        _save_csv(error_details, run_dir / "analysis/disagreement_error_details.csv")
        _save_csv(patient_summary[["sample_id", "y_true", "n_oof_events", "A_errors", "B_errors", "C_errors", "hard_vote_errors",
                                   "disagreement_events", "disagreement_rate", "n_distinct_patterns", "pattern_changed_across_repeats",
                                   "all_three_wrong_events", "only_one_model_correct_events"]],
                  run_dir / "analysis/patient_level_error_frequency.csv")
        write_stage1_report(run_dir / "analysis/disagreement_analysis_report.md", pattern_summary, patient_summary, error_details)
        require(len(fold_defs) == 100 and all(len(f["train_ids"]) == 512 and len(f["valid_ids"]) == 128 for f in fold_defs),
                "RepeatedStratifiedKFold折数/大小检查失败")
        split_probe = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        local = fold_defs[0]["train_index"]
        # 在一个实际外层训练子集上测内层分层、覆盖和ID隔离；不拟合也不访问其外层验证标签。
        probe_labels = y[local]
        inner_probe = list(split_probe.split(np.zeros(len(local)), probe_labels))
        seen = []
        for itr, iva in inner_probe:
            seen.extend(iva.tolist())
            require(not set(ids[local[itr]]) & set(ids[local[iva]]), "内层训练/验证ID交叉")
            require(len(itr) + len(iva) == len(local), "内层样本丢失")
        require(sorted(seen) == list(range(len(local))), "一次内层5折未让每名患者恰好获得一次OOF预测")
        probe = np.array([["BRCA","BRCA","BRCA"],["BRCA","BRCA","LUAD"],["BRCA","LUAD","BRCA"],
                          ["LUAD","BRCA","BRCA"],["BRCA","COAD","KIRC"]])
        require(mode_pattern(probe).tolist() == list(PATTERNS), "P0至P4逻辑单元检查失败")
        current_fold_results = pd.read_csv(source / "ensemble_fold_results.csv")
        fit_sum = float(current_fold_results.loc[current_fold_results.model.isin(["A","B","C"]), "fit_seconds"].sum())
        inner_sizes = [len(tr) for tr, _ in inner_probe]
        estimate = resource_report(pd.DataFrame(), fold_defs, data)
        estimate["historical_three_models_300_outer_fits_seconds"] = fit_sum
        estimate["mean_inner_training_samples_estimated"] = float(np.mean(inner_sizes))
        estimate["estimated_inner_fit_seconds"] = fit_sum * estimate["inner_model_fits"]/300 * np.mean(inner_sizes)/512
        estimate["estimated_outer_fit_seconds"] = fit_sum
        total_s = estimate["estimated_inner_fit_seconds"] + estimate["estimated_outer_fit_seconds"]
        estimate["estimated_total_fit_seconds"] = total_s
        estimate["estimated_end_to_end_minutes_range"] = [round(total_s*1.35/60,1), round(total_s*2.1/60,1)]
        require(matrix_bytes == 640 * 20531 * 8, "开发矩阵数值类型或大小意外")
        preflight = {"source_run": str(source), "source_identity": source_frozen["identity"],
                     "source_oof_sha256": source_oof_sha, "source_oof_rows": len(source_frame),
                     "development_fingerprint": read_json(run_dir / "development_data_record.json")["development_fingerprint_sha256"],
                     "n_development_patients": len(ids), "n_reserved_test_ids_excluded": len(data.reserved_test_ids),
                     "n_outer_folds": len(fold_defs), "inner_cv": {"splitter": "StratifiedKFold", "n_splits": 5,
                     "shuffle": True, "random_state": 42, "each_outer_train_patient_one_inner_oof": True},
                     "historical_disagreement_events": int(source_frame.pattern.ne("P0").sum()),
                     "historical_disagreement_patients": int(affected.nunique()),
                     "pattern_event_counts": {r.pattern:int(r.prediction_events) for _,r in pattern_summary.iterrows()},
                     "pattern_unique_patient_counts": {r.pattern:int(r.unique_patients) for _,r in pattern_summary.iterrows()},
                     "same_fold_union_budget_control_verified": True,
                     "same_fold_union_budget_control_rows": len(budget_audit),
                     "nested_model_fit_resource_estimate": estimate,
                     "preflight_rule_mapping_checks_passed": True,
                     "preflight_inner_stratification_and_isolation_passed": True,
                     "outer_labels_excluded_from_rule_learning_by_function_signature": True,
                     "previous_research_design_exploration_was_not_independent": True,
                     "analysis_records_reused": 100, "outer_base_estimators_will_be_refit": 300,
                     "test_set_touched": False}
        atomic_json(run_dir / "logs/preflight.json", preflight)
        _save_csv(pd.DataFrame(source_audit), run_dir / "logs/source_oof_audit.csv")
        rule_definitions = {
            "default_model": "A", "exploratory_fixed_rule": FIXED_RULE,
            "exploratory_fixed_rule_origin": "启发于已核验但已查看过的历史开发集OOF，仅作候选并分开标记",
            "learned_rule_thresholds": {"minimum_unique_patients_per_pattern": MIN_UNIQUE_PATIENTS,
                                        "minimum_net_corrected_samples_over_A": MIN_NET_CORRECTIONS},
            "candidate_models": ["A", "B", "C"], "candidate_priority_for_equal_positive_net_gain": ["B", "C"],
            "learning_unit": "one inner OOF prediction per unique outer-training sample",
            "inner_cv": "StratifiedKFold(n_splits=5, shuffle=True, random_state=42)",
            "outer_validation_labels_visible_to_rule_learner": False,
            "if_thresholds_fail": "keep A; never lower thresholds based on outer results",
            "no_probabilities_soft_voting_weights_or_model_search": True}
        atomic_json(run_dir / "logs/frozen_arbitration_rules.json", rule_definitions)
        atomic_json(run_dir / "arbitration/arbitration_rule_definitions.json", rule_definitions)
        _save_csv(pd.DataFrame(budget_audit), run_dir / "logs/matched_gene_budget_source_audit.csv")
        with (run_dir / "cv_fold_indices.json").open("w", encoding="utf-8") as f:
            json.dump({"cv_mode":"repeated", "folds":[{k:v for k,v in d.items() if not k.endswith("_index")} for d in fold_defs]}, f, ensure_ascii=False, indent=2)
        code_files = ("dynamic_arbitration.py", "dynamic_arbitration_report.py", "dynamic_arbitration_visualization.py",
                      "verify_dynamic_arbitration.py", "hard_voting.py", "config.py", "ablation_engine.py",
                      "fusion_selection.py", "baseline.py", "feature_selection.py", "variance_topk.py",
                      "cross_validation.py", "data_loader.py", "visualization.py", "evaluation.py", "ablation_report.py")
        frozen = {"protocol": "nested-training-isolated-disagreement-arbitration-v1",
                  "source_hard_voting_identity": source_frozen["identity"], "source_oof_sha256": source_oof_sha,
                  "development_fingerprint": preflight["development_fingerprint"],
                  "outer_cv": {"splitter":"RepeatedStratifiedKFold", "n_splits":5,"n_repeats":20,"random_state":42},
                  "inner_cv": preflight["inner_cv"], "base_pipeline_records": source_frozen["pipelines"],
                  "arbitration_rules": read_json(run_dir / "logs/frozen_arbitration_rules.json"),
                  "preflight": preflight, "no_test_set_access": True,
                  "packages": {p:importlib.metadata.version(p) for p in ("numpy","pandas","scikit-learn","scipy","matplotlib","joblib","threadpoolctl","pillow")},
                  "python":platform.python_version(), "code_sha256":{p:sha256(PROJECT_DIR/p) for p in code_files}}
        frozen["identity"] = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        frozen_path = run_dir / "logs/frozen_experiment.json"
        if frozen_path.exists():
            saved_frozen = read_json(frozen_path)
            if saved_frozen != frozen:
                # 仅允许此处明确审计过的输出表展开修正；任何拟合、规则或数据变化都拒绝续跑。
                saved_core, current_core = dict(saved_frozen), dict(frozen)
                saved_core.pop("identity", None); current_core.pop("identity", None)
                saved_hashes = dict(saved_core["code_sha256"]); current_hashes = dict(current_core["code_sha256"])
                saved_hashes.pop("dynamic_arbitration.py", None); current_hashes.pop("dynamic_arbitration.py", None)
                saved_hashes.pop("verify_dynamic_arbitration.py", None); current_hashes.pop("verify_dynamic_arbitration.py", None)
                saved_core["code_sha256"], current_core["code_sha256"] = saved_hashes, current_hashes
                original_script = (run_dir / "logs/source_snapshot/dynamic_arbitration.py").read_text(encoding="utf-8")
                current_script = (PROJECT_DIR / "dynamic_arbitration.py").read_text(encoding="utf-8")
                old_line = 'td.insert(0,"sample_id",p.sample_id.tolist());td.insert(0,"evaluation_id",oe)'
                new_line = 'td.insert(0,"sample_id",[sid for sid in p.sample_id.tolist() for _ in SCHEMES]);td.insert(0,"evaluation_id",oe)'
                old_start = original_script.index("        if frozen_path.exists(): require(")
                old_end = original_script.index('        atomic_json(run_dir / "logs/environment.json"', old_start)
                current_marker = current_script.index('        frozen_path = run_dir / "logs/frozen_experiment.json"')
                current_start = current_script.index('        if frozen_path.exists():\n            saved_frozen = read_json(frozen_path)', current_marker)
                current_end = current_script.rindex('        atomic_json(run_dir / "logs/environment.json"')
                normalized_current = current_script[:current_start] + original_script[old_start:old_end] + current_script[current_end:]
                repeat_ids_line = 'td.insert(0,"sample_id",[sid for sid in p.sample_id.tolist() for _ in SCHEMES]);td.insert(0,"evaluation_id",oe)'
                nan_assignment = '        historical_pattern_records=json.loads(pattern_summary.to_json(orient="records"))\n'
                prediction_aliases = '            for m in "ABC": p[f"pred_model_{m}"]=p[f"pred_{m}"]\n'
                old_summary_field = '            "historical_pattern_summary":pattern_summary.to_dict("records"),'
                new_summary_field = '            "historical_pattern_summary":historical_pattern_records,'
                allowed_output_fixes = (normalized_current.count(repeat_ids_line) == 1 and
                    normalized_current.count(nan_assignment) == 1 and normalized_current.count(new_summary_field) == 1 and
                    normalized_current.count(prediction_aliases) == 1)
                if allowed_output_fixes:
                    normalized_current = normalized_current.replace(repeat_ids_line, old_line)
                    normalized_current = normalized_current.replace(nan_assignment, "")
                    normalized_current = normalized_current.replace(new_summary_field, old_summary_field)
                    normalized_current = normalized_current.replace(prediction_aliases, "")
                original_verifier = (run_dir / "logs/source_snapshot/verify_dynamic_arbitration.py").read_text(encoding="utf-8")
                current_verifier = (PROJECT_DIR / "verify_dynamic_arbitration.py").read_text(encoding="utf-8")
                old_verifier_block = '    fold_file=read_json(run/"cv_fold_indices.json")["folds"]\n'
                new_verifier_block = ('    stored_fold_file=read_json(run/"cv_fold_indices.json")["folds"]\n'
                    '    fold_file=[{"evaluation_id":d["evaluation_id"],"repeat":d["repeat_id"],"fold":d["fold_id"],\n'
                    '        "train_sample_ids":d["train_ids"],"validation_sample_ids":d["valid_ids"]} for d in stored_fold_file]\n')
                verifier_schema_fix = original_verifier.count(old_verifier_block) == 1 and original_verifier.replace(old_verifier_block,new_verifier_block) == current_verifier
                aggregation_only_fix = original_script.count(old_line) == 1 and allowed_output_fixes and normalized_current == original_script and verifier_schema_fix
                require(args.resume is not None and saved_core == current_core and aggregation_only_fix,
                        "恢复时源码、数据、旧OOF或配置不一致；只接受已审计的触发明细展开修正")
                frozen = saved_frozen
                hotfix = {"scope":"post-fit output serialization only",
                    "changes":[
                    "repeat each outer validation sample_id once for each of seven scheme rows in trigger details",
                    "serialize undefined historical P4 accuracy as JSON null rather than nonstandard NaN",
                    "include explicit model_A/model_B/model_C prediction alias columns in the OOF export",
                    "normalize persisted outer CV fold-index field names in the independent verifier"],
                    "model_fit_or_prediction_logic_changed":False,"training_fold_or_rule_logic_changed":False,
                    "source_data_or_labels_changed":False,"all_1800_fit_checkpoints_reused":True,
                    "original_frozen_identity":saved_frozen["identity"],
                    "original_dynamic_arbitration_sha256":saved_frozen["code_sha256"]["dynamic_arbitration.py"],
                    "aggregation_hotfix_dynamic_arbitration_sha256":sha256(PROJECT_DIR/"dynamic_arbitration.py"),
                    "verification":"current script must equal frozen source snapshot after normalizing only the two explicit output fixes and this audited resume block"}
                atomic_json(run_dir/"logs/postprocessing_hotfix.json",hotfix)
                hotfix_snapshot=run_dir/"logs/postprocessing_snapshot"
                hotfix_snapshot.mkdir(parents=True,exist_ok=True)
                shutil.copy2(PROJECT_DIR/"dynamic_arbitration.py",hotfix_snapshot/"dynamic_arbitration.py")
                shutil.copy2(PROJECT_DIR/"verify_dynamic_arbitration.py",hotfix_snapshot/"verify_dynamic_arbitration.py")
                log(run_dir,"检测到仅限拟合后触发明细行展开的单行修正；冻结训练配置与其他代码哈希完全一致，将复用全部检查点而不重训。")
            else:
                frozen = saved_frozen
        else:
            atomic_json(frozen_path, frozen)
        (run_dir / "logs/source_snapshot").mkdir(parents=True, exist_ok=True)
        if not frozen_path.exists() or not (run_dir / "logs/source_snapshot/dynamic_arbitration.py").is_file():
            for filename in code_files:
                shutil.copy2(PROJECT_DIR / filename, run_dir / "logs/source_snapshot" / filename)
        atomic_json(run_dir / "logs/environment.json", {"python":platform.python_version(), "platform":platform.platform(),
                    "packages":frozen["packages"], "numeric_threads":1,
                    "all_installed_distributions":dict(sorted((d.metadata["Name"],d.version) for d in importlib.metadata.distributions() if d.metadata.get("Name")))})
        log(run_dir, f"预检完成：分歧{preflight['historical_disagreement_events']}次，涉及{preflight['historical_disagreement_patients']}人；计划1500次内层+300次外层拟合，约{estimate['estimated_end_to_end_minutes_range'][0]}–{estimate['estimated_end_to_end_minutes_range'][1]}分钟。")
        log(run_dir, "按冻结阈值启动嵌套评价；每个外层训练患者在5折内层CV恰有一次OOF，外层验证标签不传入仲裁规则学习。")
        atomic_json(run_dir / "status.json", {"status":"running_nested_cv", "started":datetime.now().isoformat(), "identity":frozen["identity"]})
        id_pos = {sid:i for i,sid in enumerate(ids)}
        out_of_fold_checkpoint_rows, inner_audit_rows, rule_rows = [], [], []
        outer_audit_rows, leakage_rows, fold_results, prediction_details = [], [], [], []
        actual_budget_audit_rows = []
        start_all = time.perf_counter()
        inner_splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        for outer_no, fd in enumerate(fold_defs, 1):
            oe, train_ids, valid_ids = fd["evaluation_id"], fd["train_ids"], fd["valid_ids"]
            train_idx, valid_idx = fd["train_index"], fd["valid_index"]
            require(not set(train_ids) & set(valid_ids) and not (set(train_ids)|set(valid_ids)) & set(data.reserved_test_ids), "外层ID隔离失败")
            inner_path_ids, inner_index, inner_records = [], {}, []
            y_train = y[train_idx]
            # StratifiedKFold仅用外层训练标签完成分层；外层验证标签不会传入splitter。
            inner_splits = list(inner_splitter.split(np.zeros(len(train_idx), dtype=np.uint8), y_train))
            for inner_fold, (itr_local, iva_local) in enumerate(inner_splits, 1):
                itr, iva = train_idx[itr_local], train_idx[iva_local]
                itr_ids, iva_ids = ids[itr].tolist(), ids[iva].tolist()
                require(not set(itr_ids)&set(iva_ids) and set(itr_ids)|set(iva_ids)==set(train_ids), "内层折ID交叉或丢失样本")
                require(not set(iva_ids)&set(valid_ids) and set(itr_ids)&set(train_ids), "外层验证ID进入内层")
                inner_path_ids.extend(iva_ids)
                inner_index.update({sid:inner_fold for sid in iva_ids})
                score_record, score_arrays = prepare_scores(X[itr], y[itr], run_dir / f"scores/inner/outer_{oe:03d}_inner_{inner_fold}",
                                                            frozen["identity"], itr_ids)
                require(score_record["training_digest"] == training_digest(X[itr],y[itr]) and score_record["sample_ids"] == itr_ids,
                        "内层训练排名缓存ID/数值顺序错误")
                current = {}
                for method in BASE_MODELS.values():
                    mid = (oe-1)*5+inner_fold
                    ck = run_dir / f"checkpoints/inner_members/outer_{oe:03d}_inner_{inner_fold}_{method}"
                    fit_result=fit_classification_task(X,y,itr,iva,method,50,mid,cfg,ck,frozen["identity"],
                                            (score_arrays["variance"],score_arrays["anova"],score_arrays["constant"]))
                    meta,arr = load_checkpoint(ck,frozen["identity"])
                    require(meta["audit"]["train_validation_overlap"]==0 and meta["audit"]["reserved_test_overlap"]==0,
                            "内层Pipeline拟合范围失败")
                    require(meta["audit"]["selector_fit_samples"]==len(itr) and meta["audit"]["scaler_training_samples"]==len(itr),
                            "内层选择器/标准化器拟合样本数错误")
                    current[method] = arr["valid_pred"]
                    inner_audit_rows.append({"layer":"inner", "outer_evaluation_id":oe,"outer_repeat_id":fd["repeat_id"],
                        "outer_fold_id":fd["fold_id"],"inner_fold_id":inner_fold,"inner_evaluation_id":mid,"model":method,
                        "n_training":len(itr),"n_validation":len(iva),"validation_ids_disjoint_from_training":True,
                        "outer_validation_ids_absent":True,"fit_audit_passed":True,"checkpoint_sha256":meta["arrays_sha256"],
                        **meta["audit"],
                        "training_digest":score_record["training_digest"],"fit_seconds":meta["metrics"]["fit_seconds"],
                        "predict_seconds_train_and_validation":meta["metrics"]["predict_seconds"],
                        "resumed_checkpoint":bool(fit_result.get("resumed",False))})
                for j,sid in enumerate(iva_ids):
                    inner_records.append({"sample_id":sid,"inner_fold_id":inner_fold,"y_true":y[iva[j]],
                        **{f"pred_{m}":current[method][j] for m,method in zip("ABC",BASE_MODELS.values())}})
            require(len(inner_path_ids)==len(train_ids) and len(set(inner_path_ids))==len(train_ids) and set(inner_path_ids)==set(train_ids),
                    "每名外层训练患者必须恰好生成一次内部OOF预测")
            inner_table=pd.DataFrame(inner_records).set_index("sample_id").loc[train_ids].reset_index()
            inner_table["outer_evaluation_id"]=oe
            inner_table["outer_repeat_id"]=fd["repeat_id"]
            inner_table["pattern"]=mode_pattern(inner_table[[f"pred_{m}" for m in "ABC"]].to_numpy())
            for m in "ABC": inner_table[f"correct_{m}"]=inner_table[f"pred_{m}"].eq(inner_table.y_true)
            rules, rule_stats=learn_rules(inner_table,train_ids,valid_ids)
            for row in rule_stats:
                rule_rows.append({**row,"outer_evaluation_id":oe,"outer_repeat_id":fd["repeat_id"],"outer_fold_id":fd["fold_id"]})
            # 验证规则在完整外层训练集拟合前即锁定，且路由API从不接收y_valid。
            atomic_json(run_dir / f"arbitration/rules_outer_{oe:03d}.json", {
                "identity":frozen["identity"],"outer_evaluation_id":oe,"outer_training_ids_sha256":hashlib.sha256(json.dumps(train_ids).encode()).hexdigest(),
                "inner_oof_ids_sha256":hashlib.sha256(json.dumps(inner_table.sample_id.tolist()).encode()).hexdigest(),
                "outer_validation_ids_used":False,"outer_validation_labels_used":False,"learned_rules":rules,"rule_statistics":rule_stats})
            score_record, score_arrays=prepare_scores(X[train_idx],y[train_idx],run_dir/f"scores/outer/outer_{oe:03d}",
                                                       frozen["identity"],train_ids)
            outer_predictions=[]
            outer_selected=[]
            for method in BASE_MODELS.values():
                ck=run_dir/f"checkpoints/outer_members/outer_{oe:03d}_{method}"
                fit_result=fit_classification_task(X,y,train_idx,valid_idx,method,50,oe,cfg,ck,frozen["identity"],
                                        (score_arrays["variance"],score_arrays["anova"],score_arrays["constant"]))
                meta,arr=load_checkpoint(ck,frozen["identity"])
                outer_predictions.append(arr["valid_pred"])
                outer_selected.append(arr["selected"])
                outer_audit_rows.append({"layer":"outer", "outer_evaluation_id":oe,"outer_repeat_id":fd["repeat_id"],
                    "outer_fold_id":fd["fold_id"],"model":method,"n_training":len(train_idx),"n_validation":len(valid_idx),
                    "outer_validation_ids_absent_from_fit":True,"selector_fit_samples":meta["audit"]["selector_fit_samples"],
                    "scaler_training_samples":meta["audit"]["scaler_training_samples"],"fit_audit_passed":True,
                    **meta["audit"],
                    "checkpoint_sha256":meta["arrays_sha256"],"fit_seconds":meta["metrics"]["fit_seconds"],
                    "predict_seconds_train_and_validation":meta["metrics"]["predict_seconds"],
                    "resumed_checkpoint":bool(fit_result.get("resumed",False))})
            actual_union = set(data.X.columns[np.unique(np.concatenate(outer_selected))].astype(str))
            require(actual_union == matched_union_by_eval[oe],
                    f"重新拟合的外层基因并集与此前同折预算对照不一致：fold {oe}")
            actual_budget_audit_rows.append({"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                "n_actual_unique_genes":len(actual_union),"n_source_union_genes":len(matched_union_by_eval[oe]),
                "exact_gene_set_match":True,"source_matched_union_svm_metrics_available":True})
            outer_matrix=np.column_stack(outer_predictions)
            source_fold_predictions = source_predictions_by_eval[oe].loc[valid_ids].to_numpy(dtype=str)
            require(np.array_equal(outer_matrix.astype(str), source_fold_predictions),
                    f"当前重新拟合预测未复现历史同一外层折预测：fold {oe}")
            outer_mode=mode_pattern(outer_matrix)
            outer_pred,trigger_rows=apply_rules(outer_matrix,outer_mode,rules)
            yvalid=y[valid_idx]  # 仅从此处起读取外层验证标签，规则和模型均已冻结/拟合。
            pred_df=pd.DataFrame({"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                "sample_id":valid_ids,"y_true":yvalid,"pred_A":outer_matrix[:,0],"pred_B":outer_matrix[:,1],"pred_C":outer_matrix[:,2],
                "pattern":outer_mode,"pattern_definition":[PATTERN_DEFINITIONS[x] for x in outer_mode]})
            pred_df["pred_hard_vote"]=outer_pred["hard_vote"]
            for scheme in SCHEMES:
                pred_df[f"pred_{scheme}"]=outer_pred[scheme]
                pred_df[f"correct_{scheme}"]=pred_df[f"pred_{scheme}"].eq(yvalid)
            pred_df["correct_A"]=pred_df.pred_model_A.eq(yvalid)
            pred_df["n_base_correct"]=pred_df[[f"correct_model_{m}" for m in "ABC"]].sum(axis=1)
            pred_df["all_base_wrong"]=pred_df.n_base_correct.eq(0)
            pred_df["only_one_base_correct"]=pred_df.n_base_correct.eq(1)
            tdetail=trigger_rows.copy()
            tdetail.insert(0,"sample_id",[sid for sid in valid_ids for _ in SCHEMES])
            tdetail.insert(0,"evaluation_id",oe)
            tdetail.insert(2,"repeat_id",fd["repeat_id"]); tdetail.insert(3,"fold_id",fd["fold_id"])
            tdetail["y_true_after_rule_freeze"]=[label for label in yvalid for _ in SCHEMES]
            tdetail["pattern_definition"]= [PATTERN_DEFINITIONS[x] for x in outer_mode for _ in SCHEMES]
            prediction_details.append((pred_df,tdetail))
            yA=pred_df.y_true.to_numpy()
            row_common={"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                        "n_training":len(train_idx),"n_validation":len(valid_idx),"n_disagreement_events":int((outer_mode!="P0").sum()),
                        "disagreement_rate":float(np.mean(outer_mode!="P0")),"n_unanimous_errors":int((pred_df.pattern.eq("P0") & ~pred_df.correct_model_A).sum()),
                        "n_disagreement_errors_A":int(((outer_mode!="P0") & ~pred_df.correct_model_A).sum()),
                        "disagreement_error_rate_A":float((~pred_df.loc[outer_mode!="P0","correct_model_A"]).mean()) if np.any(outer_mode!="P0") else np.nan,
                        "mean_distinct_genes_three_models":int(len(set(np.concatenate(outer_selected)))),
                        "inner_oof_seconds":float(sum(a["fit_seconds"]+a["predict_seconds_train_and_validation"] for a in inner_audit_rows if a["outer_evaluation_id"]==oe)),
                        "outer_three_model_fit_seconds":float(sum(a["fit_seconds"] for a in outer_audit_rows if a["outer_evaluation_id"]==oe)),
                        "rule_training_n_inner_oof_patients":len(inner_table),
                        "rule_training_disagreement_patients":int(inner_table.loc[inner_table.pattern.ne("P0"),"sample_id"].nunique()),
                        "n_rules_overrode_A":int(sum(v!="A" for v in rules.values())),
                        "rules_are_consensus_default_or_evidence_supported":True}
            for scheme in SCHEMES:
                v=fast_scores(yA,pred_df[f"pred_{scheme}"].to_numpy())
                changed=(pred_df.correct_model_A != pred_df[f"correct_{scheme}"])
                row={**row_common,"scheme":scheme,"scheme_name":SCHEME_LABELS[scheme],
                     "n_arbitration_triggers":int(tdetail.loc[tdetail.scheme.eq(scheme),"triggered"].sum()),
                     "arbitration_trigger_rate":float(tdetail.loc[tdetail.scheme.eq(scheme),"triggered"].mean()),
                     "n_corrected_vs_A":int((~pred_df.correct_model_A & pred_df[f"correct_{scheme}"]).sum()),
                     "n_new_errors_vs_A":int((pred_df.correct_model_A & ~pred_df[f"correct_{scheme}"]).sum()),
                     "n_events_changed_from_A":int((pred_df[f"pred_{scheme}"]!=pred_df.pred_model_A).sum()),
                     "vote_rule_ties":int(tdetail.loc[tdetail.scheme.eq(scheme),"tie_rule_applied"].sum()),
                     "fit_seconds":row_common["outer_three_model_fit_seconds"] if scheme in ("hard_vote","fixed_disagreement","learned_inner_oof","conservative_fallback") else next(a["fit_seconds"] for a in outer_audit_rows if a["outer_evaluation_id"]==oe and a["model"]==BASE_MODELS[scheme[-1]]) if scheme.startswith("model_") else 0.,
                     **v}
                fold_results.append(row)
            leakage_rows.append({"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                "outer_train_ids":len(train_ids),"outer_validation_ids":len(valid_ids),
                "outer_train_validation_overlap":0,"reserved_id_overlap":0,
                "inner_oof_covered_each_outer_train_id_once":True,"inner_fit_rows_subset_outer_train":True,
                "inner_scaler_and_selector_fit_inside_inner_training_folds":True,"rules_fit_from_inner_oof_y_only":True,
                "outer_validation_labels_used_for_rule":False,"outer_validation_labels_accessed_only_after_rule_frozen":True,
                "outer_pipeline_fit_only_outer_training_ids":True,"member_prediction_ids_identical":True,
                "one_true_label_per_patient":True,"outer_validation_results_scored_after_freeze":True})
            # 每完成一外折就存完整内层/外层预测和规则，支持中断后安全恢复。
            save_checkpoint(run_dir/f"checkpoints/outer_{oe:03d}",{"identity":frozen["identity"],"evaluation_id":oe,
                "repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],"train_ids":train_ids,"valid_ids":valid_ids,
                "rules":rules,"rule_stats":rule_stats,"source_oof_sha256":source_oof_sha,
                "outer_validation_labels_used_for_rule":False,"rule_locked_before_outer_fit":True,
                "outer_genes_union_count":row_common["mean_distinct_genes_three_models"],
                "inner_fit_audits":[a for a in inner_audit_rows if a["outer_evaluation_id"]==oe],
                "outer_fit_audits":[a for a in outer_audit_rows if a["outer_evaluation_id"]==oe]},
                inner_predictions=inner_table[[f"pred_{m}" for m in "ABC"]].to_numpy(dtype="U8"),
                inner_true=inner_table.y_true.to_numpy(dtype="U8"),inner_ids=inner_table.sample_id.to_numpy(dtype="U16"),
                inner_fold=inner_table.inner_fold_id.to_numpy(dtype=np.int8),
                inner_pattern=inner_table.pattern.to_numpy(dtype="U2"),outer_predictions=outer_matrix,
                outer_true=yvalid.astype("U8"),outer_ids=np.asarray(valid_ids,dtype="U16"),
                selected=np.stack(outer_selected),outer_pattern=outer_mode.astype("U2"),
                predicted_A=outer_pred["model_A"],predicted_B=outer_pred["model_B"],predicted_C=outer_pred["model_C"],
                predicted_hard_vote=outer_pred["hard_vote"],predicted_fixed=outer_pred["fixed_disagreement"],
                predicted_learned=outer_pred["learned_inner_oof"],predicted_conservative=outer_pred["conservative_fallback"],
                trigger=np.column_stack([tdetail.loc[tdetail.scheme.eq(s),"triggered"].to_numpy() for s in SCHEMES]))
            if outer_no==1 or outer_no%5==0:
                elapsed=time.perf_counter()-start_all
                log(run_dir,f"外层折{outer_no}/100已完成；已训练{outer_no*18}个Pipeline，本阶段耗时{elapsed/60:.1f}分钟。")
        # Rebuild all outputs from integrity-checked per-fold checkpoints for consistent resume behavior.
        inner_parts=[]; outer_parts=[]; trigger_parts=[]; rule_records=[]; nested_audits=[]; outer_audits=[]; leak_records=[]
        for fd in fold_defs:
            oe=fd["evaluation_id"]
            meta,a=load_checkpoint(run_dir/f"checkpoints/outer_{oe:03d}",frozen["identity"])
            inner= pd.DataFrame({"sample_id":a["inner_ids"].astype(str),"y_true":a["inner_true"].astype(str),
                "inner_fold_id":a["inner_fold"],"outer_evaluation_id":oe,"outer_repeat_id":fd["repeat_id"],
                "pattern":a["inner_pattern"].astype(str),**{f"pred_{m}":a["inner_predictions"][:,i].astype(str) for i,m in enumerate("ABC")}})
            for m in "ABC": inner[f"correct_{m}"]=inner[f"pred_{m}"].eq(inner.y_true)
            inner_parts.append(inner)
            p=pd.DataFrame({"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                "sample_id":a["outer_ids"].astype(str),"y_true":a["outer_true"].astype(str),"pattern":a["outer_pattern"].astype(str),
                **{f"pred_{m}":a[f"predicted_{m}"].astype(str) for m in "ABC"},
                "pred_hard_vote":a["predicted_hard_vote"].astype(str),"pred_fixed_disagreement":a["predicted_fixed"].astype(str),
                "pred_learned_inner_oof":a["predicted_learned"].astype(str),"pred_conservative_fallback":a["predicted_conservative"].astype(str)})
            for m in "ABC": p[f"pred_model_{m}"]=p[f"pred_{m}"]
            for scheme in SCHEMES:
                col={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
                     "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
                     "conservative_fallback":"pred_conservative_fallback"}[scheme]
                p[f"correct_{scheme}"]=p[col].eq(p.y_true)
            p["n_base_correct"]=p[[f"correct_model_{m}" for m in "ABC"]].sum(axis=1)
            p["all_base_wrong"]=p.n_base_correct.eq(0);p["only_one_base_correct"]=p.n_base_correct.eq(1)
            outer_parts.append(p)
            ids_rule=meta["rules"]
            for row in meta["rule_stats"]: rule_records.append({**row,"outer_evaluation_id":oe,"outer_repeat_id":fd["repeat_id"],"outer_fold_id":fd["fold_id"]})
            nested_audits.extend(meta["inner_fit_audits"]);outer_audits.extend(meta["outer_fit_audits"])
            leak_records.append({"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                "outer_train_ids":len(meta["train_ids"]),"outer_validation_ids":len(meta["valid_ids"]),
                "outer_train_validation_overlap":0,"reserved_id_overlap":0,
                "inner_oof_covered_each_outer_train_id_once":True,"inner_fit_rows_subset_outer_train":True,
                "inner_scaler_and_selector_fit_inside_inner_training_folds":True,"rules_fit_from_inner_oof_y_only":True,
                "outer_validation_labels_used_for_rule":False,"outer_validation_labels_accessed_only_after_rule_frozen":True,
                "outer_pipeline_fit_only_outer_training_ids":True,"member_prediction_ids_identical":True,
                "one_true_label_per_patient":True,"outer_validation_results_scored_after_freeze":True})
        inner_all=pd.concat(inner_parts,ignore_index=True)
        outer_all=pd.concat(outer_parts,ignore_index=True)
        inner_all["all_three_wrong"]=~inner_all[[f"correct_{m}" for m in "ABC"]].any(axis=1)
        inner_all["n_base_correct"]=inner_all[[f"correct_{m}" for m in "ABC"]].sum(axis=1)
        _save_csv(inner_all,run_dir/"arbitration/inner_oof_predictions.csv")
        _save_csv(pd.DataFrame(rule_records),run_dir/"arbitration/learned_rules_by_outer_fold.csv")
        _save_csv(outer_all,run_dir/"evaluation/arbitration_oof_predictions.csv")
        _save_csv(pd.DataFrame(nested_audits+outer_audits),run_dir/"logs/arbitration_fit_audit.csv")
        _save_csv(pd.DataFrame(leak_records),run_dir/"logs/data_leakage_audit.csv")
        _save_csv(pd.DataFrame(actual_budget_audit_rows),run_dir/"logs/matched_gene_budget_actual_audit.csv")
        # Trigger details are reconstructed from immutable fold checkpoints; only now attach y for outcome auditing.
        for fd,pair in zip(fold_defs,prediction_details):
            _,td=pair
            # `prediction_details` only contains the current process; recovered runs rebuild below from each checkpoint.
        trigger_records=[]; fold_metric_rows=[]; perclass_rows=[]; confusion_rows=[]; change_rows=[]
        id_rank={sid:i for i,sid in enumerate(ids)}
        for fd,p in zip(fold_defs,outer_parts):
            oe=fd["evaluation_id"]
            meta,a=load_checkpoint(run_dir/f"checkpoints/outer_{oe:03d}",frozen["identity"])
            matrix=a["outer_predictions"].astype(str); patterns=a["outer_pattern"].astype(str)
            learned=meta["rules"]
            _,td=apply_rules(matrix,patterns,learned)
            # Both arbitration and routing ran without y; labels are added to saved audit only after prediction freeze.
            td.insert(0,"sample_id",[sid for sid in p.sample_id.tolist() for _ in SCHEMES]);td.insert(0,"evaluation_id",oe)
            td.insert(2,"repeat_id",fd["repeat_id"]);td.insert(3,"fold_id",fd["fold_id"])
            td["pattern_definition"]=[PATTERN_DEFINITIONS[x] for x in patterns for _ in SCHEMES]
            td["y_true_after_prediction_freeze"]=[value for value in p.y_true for _ in SCHEMES]
            trigger_records.extend(td.to_dict("records"))
            for scheme in SCHEMES:
                col={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
                     "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
                     "conservative_fallback":"pred_conservative_fallback"}[scheme]
                true=p.y_true.to_numpy();pred=p[col].to_numpy()
                tr=td.loc[td.scheme.eq(scheme)]
                corrected=(~p.correct_model_A & p[f"correct_{scheme}"]).to_numpy()
                new=(p.correct_model_A & ~p[f"correct_{scheme}"]).to_numpy()
                row={"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],"scheme":scheme,
                    "scheme_name":SCHEME_LABELS[scheme],"n_training":512,"n_validation":128,
                    "n_disagreement_events":int(np.sum(patterns!="P0")),"disagreement_rate":float(np.mean(patterns!="P0")),
                    "n_unanimous_errors":int(((patterns=="P0") & ~p.correct_model_A.to_numpy()).sum()),
                    "disagreement_error_rate":float((~p.loc[patterns!="P0","correct_model_A"]).mean()) if np.any(patterns!="P0") else np.nan,
                    "n_arbitration_triggers":int(tr.triggered.sum()),"arbitration_trigger_rate":float(tr.triggered.mean()),
                    "n_corrected_vs_A":int(corrected.sum()),"n_new_errors_vs_A":int(new.sum()),
                    "n_net_errors_reduced_vs_A":int(corrected.sum()-new.sum()),
                    "corrected_unique_patients":int(p.loc[corrected,"sample_id"].nunique()),
                    "new_error_unique_patients":int(p.loc[new,"sample_id"].nunique()),
                    "mean_distinct_genes_three_models":len(set(a["selected"].ravel())),
                    "outer_three_model_fit_seconds":sum(r["fit_seconds"] for r in meta["outer_fit_audits"]),
                    "inner_oof_model_fit_seconds":sum(r["fit_seconds"] for r in meta["inner_fit_audits"]),
                    "inner_oof_total_fit_and_predict_seconds":sum(r["fit_seconds"]+r["predict_seconds_train_and_validation"] for r in meta["inner_fit_audits"]),
                    "rule_eligible_modes":sum(1 for v in learned.values() if v!="A"), **fast_scores(true,pred)}
                if scheme.startswith("model_"):
                    model_key=scheme[-1]
                    fitrow=next(r for r in meta["outer_fit_audits"] if r["model"]==BASE_MODELS[model_key])
                    row["outer_model_fit_seconds"]=fitrow["fit_seconds"]
                else: row["outer_model_fit_seconds"]=row["outer_three_model_fit_seconds"]
                fold_metric_rows.append(row)
                from ablation_results import class_metrics
                from sklearn.metrics import confusion_matrix
                precision_rows=class_metrics(true,pred,{"scheme":scheme,"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],"level":"outer_fold"})
                perclass_rows.extend(precision_rows)
                cm=confusion_matrix(true,pred,labels=list(CLASS_ORDER))
                confusion_rows.extend({"scheme":scheme,"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],
                    "level":"outer_fold","true_label":c,"predicted_label":d,"count":int(cm[i,j])}
                    for i,c in enumerate(CLASS_ORDER) for j,d in enumerate(CLASS_ORDER))
                for idx in np.flatnonzero(corrected|new):
                    change_rows.append({"evaluation_id":oe,"repeat_id":fd["repeat_id"],"fold_id":fd["fold_id"],"scheme":scheme,
                        "change":"corrected" if corrected[idx] else "new_error","sample_id":p.sample_id.iloc[idx],"y_true":true[idx],
                        "pattern":patterns[idx],"pred_A":p.pred_A.iloc[idx],"pred_B":p.pred_B.iloc[idx],"pred_C":p.pred_C.iloc[idx],
                        "pred_method":pred[idx],"triggered":bool(tr.triggered.iloc[idx]),"trigger_reason":tr.trigger_reason.iloc[idx]})
        fold_table=pd.DataFrame(fold_metric_rows)
        round_rows=[]; pooled_perclass=[]; pooled_conf=[]
        for repeat,g in outer_all.groupby("repeat_id",sort=True):
            require(len(g)==g.sample_id.nunique()==640 and set(g.sample_id)==set(ids), "外层一轮OOF未完整覆盖640名开发患者")
            for scheme in SCHEMES:
                col={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
                     "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
                     "conservative_fallback":"pred_conservative_fallback"}[scheme]
                pred=g[col].to_numpy();true=g.y_true.to_numpy()
                trigger_map={"model_A":False,"model_B":False,"model_C":False,"hard_vote":False}
                trigger_subset=pd.DataFrame(trigger_records)
                tr=trigger_subset.loc[trigger_subset.repeat_id.eq(repeat)&trigger_subset.scheme.eq(scheme)]
                corr=(~g.correct_model_A & g[f"correct_{scheme}"]);new=(g.correct_model_A&~g[f"correct_{scheme}"])
                round_rows.append({"repeat_id":int(repeat),"scheme":scheme,"scheme_name":SCHEME_LABELS[scheme],"n_samples":640,
                    "n_disagreement_events":int(g.pattern.ne("P0").sum()),"disagreement_rate":float(g.pattern.ne("P0").mean()),
                    "n_arbitration_triggers":int(tr.triggered.sum()),"arbitration_trigger_rate":float(tr.triggered.mean()),
                    "n_corrected_vs_A":int(corr.sum()),"n_new_errors_vs_A":int(new.sum()),
                    "n_net_errors_reduced_vs_A":int(corr.sum()-new.sum()),**fast_scores(true,pred)})
                from ablation_results import class_metrics
                pooled_perclass.extend(class_metrics(true,pred,{"scheme":scheme,"evaluation_id":0,"repeat_id":int(repeat),"fold_id":0,"level":"round_oof"}))
                from sklearn.metrics import confusion_matrix
                cm=confusion_matrix(true,pred,labels=list(CLASS_ORDER))
                pooled_conf.extend({"scheme":scheme,"evaluation_id":0,"repeat_id":int(repeat),"fold_id":0,"level":"round_oof",
                    "true_label":c,"predicted_label":d,"count":int(cm[i,j])} for i,c in enumerate(CLASS_ORDER) for j,d in enumerate(CLASS_ORDER))
        round_table=pd.DataFrame(round_rows)
        # 全部OOF预测事件层的逐类统计明确标识为重复事件汇总。
        from ablation_results import class_metrics
        from sklearn.metrics import confusion_matrix
        for scheme in SCHEMES:
            col={"model_A":"pred_A","model_B":"pred_B","model_C":"pred_C","hard_vote":"pred_hard_vote",
                 "fixed_disagreement":"pred_fixed_disagreement","learned_inner_oof":"pred_learned_inner_oof",
                 "conservative_fallback":"pred_conservative_fallback"}[scheme]
            pooled_perclass.extend(class_metrics(outer_all.y_true,outer_all[col],{"scheme":scheme,"evaluation_id":0,"repeat_id":0,"fold_id":0,"level":"pooled_repeated_outer_oof_events"}))
            cm=confusion_matrix(outer_all.y_true,outer_all[col],labels=list(CLASS_ORDER))
            pooled_conf.extend({"scheme":scheme,"evaluation_id":0,"repeat_id":0,"fold_id":0,"level":"pooled_repeated_outer_oof_events",
                "true_label":c,"predicted_label":d,"count":int(cm[i,j])} for i,c in enumerate(CLASS_ORDER) for j,d in enumerate(CLASS_ORDER))
        trigger_table=pd.DataFrame(trigger_records)
        _save_csv(trigger_table,run_dir/"arbitration/arbitration_trigger_details.csv")
        _save_csv(fold_table,run_dir/"evaluation/arbitration_fold_results.csv")
        _save_csv(round_table,run_dir/"evaluation/arbitration_round_results.csv")
        _save_csv(pd.DataFrame(perclass_rows+pooled_perclass),run_dir/"evaluation/arbitration_per_class_metrics.csv")
        _save_csv(pd.DataFrame(confusion_rows+pooled_conf),run_dir/"evaluation/arbitration_confusion_matrices.csv")
        _save_csv(pd.DataFrame(change_rows),run_dir/"evaluation/arbitration_error_changes.csv")
        desc=[]
        for scheme in SCHEMES:
            for level,tab,prefix in (("outer_fold",fold_table.loc[fold_table.scheme.eq(scheme)],""),
                                      ("round_oof",round_table.loc[round_table.scheme.eq(scheme)],"")):
                for metric in ("macro_f1","balanced_accuracy","accuracy","n_disagreement_events","disagreement_rate",
                               "n_arbitration_triggers","arbitration_trigger_rate","n_corrected_vs_A","n_new_errors_vs_A",
                               "n_net_errors_reduced_vs_A","fit_seconds","inner_oof_total_fit_and_predict_seconds"):
                    if metric not in tab: continue
                    val=tab[metric].dropna()
                    if len(val): desc.append({"scheme":scheme,"scheme_name":SCHEME_LABELS[scheme],"level":level,"metric":metric,
                        "n":len(val),"mean":val.mean(),"std":val.std(ddof=1),"min":val.min(),"max":val.max(),"median":val.median(),
                        "p05":val.quantile(.05),"p25":val.quantile(.25),"p75":val.quantile(.75),"p95":val.quantile(.95)})
        summary_table=pd.DataFrame(desc)
        _save_csv(summary_table,run_dir/"evaluation/arbitration_summary.csv")
        from dynamic_arbitration_report import finalize_outputs
        from dynamic_arbitration_visualization import plot_all
        from verify_dynamic_arbitration import verify_run
        historical_pattern_records=json.loads(pattern_summary.to_json(orient="records"))
        preliminary={"run_directory":str(run_dir),"identity":frozen["identity"],"source_oof_sha256":source_oof_sha,
            "n_development":640,"n_reserved_excluded":161,"n_outer_folds":100,"n_inner_folds":500,
            "n_inner_base_model_fits":1500,"n_outer_base_model_fits":300,"n_pipeline_fits":1800,
            "historical_disagreement_events":preflight["historical_disagreement_events"],
            "historical_disagreement_patients":preflight["historical_disagreement_patients"],
            "historical_pattern_summary":historical_pattern_records,
            "outer_model_fits_seconds":float(fold_table.loc[fold_table.scheme.eq("model_A"),"outer_three_model_fit_seconds"].sum()),
            "inner_model_fit_seconds":float(sum(a["fit_seconds"] for a in nested_audits)),
            "inner_model_predict_seconds_train_and_validation":float(sum(a["predict_seconds_train_and_validation"] for a in nested_audits)),
            "inner_model_fit_and_predict_seconds":float(sum(a["fit_seconds"]+a["predict_seconds_train_and_validation"] for a in nested_audits)),
            "outer_validation_genebudget":{"mean":float(fold_table.loc[fold_table.scheme.eq("model_A"),"mean_distinct_genes_three_models"].mean()),
                "min":int(fold_table.loc[fold_table.scheme.eq("model_A"),"mean_distinct_genes_three_models"].min()),
                "max":int(fold_table.loc[fold_table.scheme.eq("model_A"),"mean_distinct_genes_three_models"].max())},
            "cv_fit_time_seconds":time.perf_counter()-start_all,
            "no_independent_sample_significance_test":True,"reserved_test_evaluated":False,
            "fixed_rule_is_exploratory_historical_inspired":True}
        atomic_json(run_dir/"evaluation/arbitration_metrics_pre_report.json",preliminary)
        plot_all(run_dir)
        verification=verify_run(run_dir)
        final=finalize_outputs(run_dir,preliminary,verification)
        atomic_json(run_dir/"status.json",{"status":"complete","completed":datetime.now().isoformat(),
                    "identity":frozen["identity"],"new_pipeline_fits":1800,"reserved_test_evaluated":False})
        atomic_json(cfg.output_dir/"latest_dynamic_arbitration.json",{"run_directory":str(run_dir.relative_to(cfg.output_dir)),"status":"complete"})
        log(run_dir,f"全部阶段完成；自动隔离审计{verification['checks_passed']}项通过；输出：{run_dir}")
        return run_dir
    except Exception as exc:
        atomic_json(run_dir/"status.json",{"status":"failed","error":f"{type(exc).__name__}: {exc}","time":datetime.now().isoformat()})
        log(run_dir,traceback.format_exc())
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run",help="已完成硬投票实验目录；默认使用成功指针")
    parser.add_argument("--resume",help="恢复同一配置目录，源码/数据/OOF变化会拒绝续跑")
    run(parser.parse_args())


if __name__=="__main__": main()
