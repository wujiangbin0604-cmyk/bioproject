# -*- coding: utf-8 -*-
"""独立验收：Counter实现投票、sklearn重算指标，核对患者、事件、基因和源哈希。"""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.base import clone, is_classifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score

from ablation_engine import atomic_json, load_checkpoint, read_json, sha256
from config import CLASS_ORDER


def verify(run):
    # 此模块故意不用 vote_labels / fast_scores 生成期实现来计算期望答案。
    from hard_voting import ThreeModelHardVotingClassifier, vote_labels
    checks = 0

    def check(condition, message):
        nonlocal checks
        if not condition:
            raise AssertionError(message)
        checks += 1

    def close(actual, expected, message):
        check(bool(np.isclose(actual, expected, rtol=1e-12, atol=1e-12)), message)

    def independent_scores(y, p):
        return {"macro_f1": f1_score(y, p, average="macro", zero_division=0),
                "balanced_accuracy": balanced_accuracy_score(y, p), "accuracy": accuracy_score(y, p)}

    run = Path(run)
    frozen = read_json(run / "logs/frozen_experiment.json")
    identity = frozen["identity"]
    check(frozen["tie_rule"] == "all three distinct -> A; frozen before vote evaluation", "预设平票规则被改变")
    triples = np.array(list(product(CLASS_ORDER, repeat=3)))
    actual, flags = vote_labels(triples)
    for i, triple in enumerate(triples):
        counts = Counter(triple)
        expected = triple[0] if len(counts) == 3 else counts.most_common(1)[0][0]
        check(actual[i] == expected, "五类标签125种组合的投票规则错误")
        check(flags["tie_rule_applied"][i] == (len(counts) == 3), "平票标志错误")
    model = clone(ThreeModelHardVotingClassifier())
    check(is_classifier(model) and not hasattr(model, "estimators_"), "分类器clone或类型不符")
    manifest = read_json(run / "split_manifest.json")
    dev, reserved = manifest["development_ids"], manifest["reserved_test_ids"]
    check(len(dev) == len(set(dev)) == 640 and len(reserved) == len(set(reserved)) == 161, "划分数量异常")
    check(not set(dev) & set(reserved), "开发/保留ID交叉")
    record = read_json(run / "development_data_record.json")
    check(record["strict_development_rows_only_parsed"] and not record["reserved_values_analyzed"] and not record["reserved_labels_analyzed"], "保留数据访问审计不符")
    check(record["development_fingerprint_sha256"] == frozen["development_fingerprint"], "开发数据指纹不符")
    oof = pd.read_csv(run / "ensemble_oof_predictions.csv")
    fold_results = pd.read_csv(run / "ensemble_fold_results.csv")
    round_results = pd.read_csv(run / "ensemble_round_results.csv")
    features = pd.read_csv(run / "ensemble_feature_union.csv")
    selected = pd.read_csv(run / "ensemble_selected_features_by_fold.csv")
    audit = pd.read_csv(run / "ensemble_fit_audit.csv")
    samples = pd.read_csv(run / "ensemble_sample_prediction_stability.csv")
    summary = read_json(run / "ensemble_summary.json")
    definitions = read_json(run / "cv_fold_indices.json")["folds"]
    truth = oof.drop_duplicates("sample_id").set_index("sample_id").y_true
    check(len(oof) == 12800 and not oof.duplicated(["repeat_id", "sample_id"]).any(), "OOF重复或缺失")
    check(set(oof.sample_id) == set(dev) and not set(oof.sample_id) & set(reserved), "OOF包含非开发患者")
    check(oof.groupby("sample_id").size().eq(20).all(), "患者不是恰好20次OOF")
    check(oof.groupby("sample_id").y_true.nunique().eq(1).all(), "同一患者真实标签变化")
    check(len(fold_results) == 400 and len(round_results) == 80 and len(audit) == 400, "四模型折/轮/审计行数异常")
    check(len(selected) == 15000 and len(features) == 100, "选中特征记录不完整")
    for d in definitions:
        e = d["evaluation_id"]
        tr, va = d["train_sample_ids"], d["validation_sample_ids"]
        check(len(tr) == len(set(tr)) == 512 and len(va) == len(set(va)) == 128, "折大小异常")
        check(not set(tr) & set(va) and set(tr) | set(va) == set(dev), "折内样本隔离失败")
        check(not (set(tr) | set(va)) & set(reserved), "折中出现保留ID")
        meta, arrays = load_checkpoint(run / f"checkpoints/fold_{e:03d}", identity)
        check(meta["repeat_id"] == d["repeat"] and meta["fold_id"] == d["fold"], "断点折标识异常")
        for p in meta["provenance"]:
            check(sha256(p["json"]) == p["json_sha256"], "源JSON改变")
            check(sha256(p["npz"]) == p["npz_sha256"], "源预测NPZ改变")
        current = oof.loc[oof.evaluation_id.eq(e)].set_index("sample_id").loc[va]
        check(current.repeat_id.eq(d["repeat"]).all() and current.fold_id.eq(d["fold"]).all(), "OOF折号不符")
        check(current.y_true.tolist() == truth.loc[va].tolist(), "真实标签顺序错误")
        check(arrays["train_predictions"].shape == (512, 3) and arrays["valid_predictions"].shape == (128, 3), "成员预测数不为3")
        for part, matrix, vote, ids in (("train", arrays["train_predictions"], arrays["train_vote"], tr),
                                        ("validation", arrays["valid_predictions"], arrays["valid_vote"], va)):
            expected = []
            for i, triple in enumerate(matrix):
                counts = Counter(triple)
                expected.append(triple[0] if len(counts) == 3 else counts.most_common(1)[0][0])
                check(arrays[f"{part}_tie_rule_applied"][i] == (len(counts) == 3), "断点平票标识不符")
                check(arrays[f"{part}_has_majority"][i] == (len(counts) < 3), "多数标识不符")
                check(arrays[f"{part}_winning_vote_count"][i] == counts[expected[-1]], "票数不符")
            check(np.array_equal(vote, expected), "投票不符合固定规则")
            for i, model_name in enumerate(("A", "B", "C", "vote")):
                p = matrix[:, i] if i < 3 else vote
                row = fold_results.loc[fold_results.evaluation_id.eq(e) & fold_results.model.eq(model_name)].iloc[0]
                for metric, value in independent_scores(truth.loc[ids], p).items():
                    close(row[f"{part}_{metric}"], value, "独立sklearn重算折指标不符")
                if part == "validation":
                    check(current[f"pred_{model_name}"].tolist() == list(p), "OOF预测顺序不符")
                if i < 3:
                    source_base = Path(meta["provenance"][i]["npz"])
                    with np.load(source_base, allow_pickle=False) as original:
                        check(np.array_equal(p, original["train_pred" if part == "train" else "valid_pred"]), "成员源预测不符")
                        check(np.array_equal(arrays["selected"][i], original["selected"]), "成员源基因不同")
        for i, model_name in enumerate("ABC"):
            genes = arrays["selected"][i]
            check(len(genes) == len(set(genes)) == 50 and min(genes) >= 0 and max(genes) < 20531, "成员基因异常")
            saved = selected.loc[selected.evaluation_id.eq(e) & selected.model.eq(model_name)]
            check(saved.gene_id.tolist() == [f"gene_{g}" for g in genes], "原始基因名称或顺序改变")
        check(np.array_equal(arrays["selected"][0], arrays["selected"][2]), "A/C选择不一致")
        union = set(arrays["selected"].ravel())
        check(set(arrays["union"]) == union, "系统基因并集错误")
        fr = features.loc[features.evaluation_id.eq(e)].iloc[0]
        check(fr.n_distinct_genes_system == len(union), "基因预算错误")
        check(fr.ANOVA_variance_intersection == len(set(arrays["selected"][0]) & set(arrays["selected"][1])), "基因交集错误")
    for repeat, group in oof.groupby("repeat_id"):
        check(len(group) == group.sample_id.nunique() == 640 and set(group.sample_id) == set(dev), "一轮OOF未覆盖完整开发集")
        for model_name in ("A", "B", "C", "vote"):
            row = round_results.loc[round_results.repeat_id.eq(repeat) & round_results.model.eq(model_name)].iloc[0]
            for metric, value in independent_scores(group.y_true, group[f"pred_{model_name}"]).items():
                close(row[f"oof_{metric}"], value, "OOF轮指标错误")
            check(row.oof_error_count == (~group[f"correct_{model_name}"]).sum(), "轮错误次数错误")
    for model_name in ("A", "B", "C", "vote"):
        check(oof[f"correct_{model_name}"].eq(oof[f"pred_{model_name}"].eq(oof.y_true)).all(), "正确性标识错误")
        s = samples.loc[samples.model.eq(model_name)].set_index("sample_id")
        errors = (~oof[f"correct_{model_name}"]).groupby(oof.sample_id).sum()
        check(s.error_count.loc[errors.index].eq(errors).all(), "患者错误次数错误")
        check(s.n_oof_predictions.eq(20).all() and np.allclose(s.error_proportion, s.error_count / 20), "患者错误频率错误")
        check(summary["models"][model_name]["oof_error_events"] == int(errors.sum()), "汇总错误数错误")
        for level, table, prefix in (("validation_fold", fold_results, "validation_"), ("round_oof", round_results, "oof_")):
            g = table.loc[table.model.eq(model_name)]
            for metric in ("macro_f1", "balanced_accuracy", "accuracy"):
                values = g[prefix + metric]
                actual = summary["models"][model_name][level][metric]
                for k, value in (("mean", values.mean()), ("std", values.std(ddof=1)), ("min", values.min()), ("max", values.max()), ("median", values.median())):
                    close(actual[k], value, "描述统计错误")
    corr = pd.read_csv(run / "ensemble_correction_summary.csv").set_index("reference_model")
    changes = pd.read_csv(run / "ensemble_corrected_and_new_errors.csv")
    for model_name in "ABC":
        corrected = ~oof[f"correct_{model_name}"] & oof.correct_vote
        added = oof[f"correct_{model_name}"] & ~oof.correct_vote
        check(corr.loc[model_name, "corrected_events"] == corrected.sum(), "纠错次数错误")
        check(corr.loc[model_name, "new_error_events"] == added.sum(), "新增错误次数错误")
        check(corr.loc[model_name, "net_error_change_vote_minus_base"] == added.sum() - corrected.sum(), "净错误变化错误")
        check(len(changes.loc[changes.reference_model.eq(model_name)]) == corrected.sum() + added.sum(), "受影响事件明细遗漏")
    check(oof.base_error_count.eq(3 - oof[[f"correct_{m}" for m in "ABC"]].sum(axis=1)).all(), "基础模型错误数量不符")
    check(int(oof.unanimous.sum() + ((~oof.unanimous) & (~oof.all_three_different)).sum() + oof.all_three_different.sum()) == 12800, "一致性类别未完整划分")
    matrices = pd.read_csv(run / "ensemble_confusion_matrices.csv")
    for (level, model_name, e, repeat), g in matrices.groupby(["level", "model", "evaluation_id", "repeat_id"]):
        expected = {"training_fold": 512, "validation_fold": 128, "round_oof": 640, "pooled_repeated_OOF_events": 12800}[level]
        check(len(g) == 25 and g["count"].sum() == expected, "混淆矩阵缺失或重复计数")
    check(audit.reserved_expression_rows_parsed.eq(0).all() and audit.reserved_label_rows_parsed.eq(0).all(), "保留样本被解析")
    pngs, pdfs = sorted((run / "figures").glob("*.png")), sorted((run / "figures").glob("*.pdf"))
    check(len(pngs) == len(pdfs) == 7, "不是七组PNG/PDF")
    dimensions = []
    for png in pngs:
        with Image.open(png) as im:
            dpi = im.info.get("dpi", (0, 0))
            check(min(dpi) >= 329, "PNG分辨率低于330 DPI舍入范围")
            check(im.width > 2000 and im.height > 1200, "图像尺寸异常")
            dimensions.append({"file": png.name, "width": im.width, "height": im.height, "dpi": list(dpi)})
        check(png.with_suffix(".pdf").read_bytes().startswith(b"%PDF"), "矢量PDF格式错误")
    result = {"status": "passed", "checks_passed": checks, "patient_repeat_events": 12800,
              "unique_patients": 640, "all_125_vote_combinations_checked": True,
              "metrics_independently_recomputed_with_sklearn": True, "figures": dimensions,
              "reserved_test_evaluated": False, "significance_tests_performed": False}
    atomic_json(run / "verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    print(verify(parser.parse_args().run))
