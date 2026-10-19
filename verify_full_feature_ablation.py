# -*- coding: utf-8 -*-
"""无模型重训的完整验收：预测、索引、排名、集合、统计和图片元数据。"""
from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.feature_selection import f_classif
from sklearn.model_selection import StratifiedShuffleSplit
from threadpoolctl import threadpool_limits

from ablation_engine import METHODS, SELECTORS, atomic_json, load_checkpoint, rank_scores, read_json, scores
from config import CLASS_ORDER
from cross_validation import make_cv
from repeated_cv import descriptive


def verify(run, data, cfg, identity):
    checks = []
    def check(condition, name):
        if not bool(condition):
            raise AssertionError(f"验收失败：{name}")
        checks.append(name)
    X, y = data.X.to_numpy(dtype=float), data.y.to_numpy(dtype=str)
    ids, genes = data.X.index.to_numpy(dtype=str), data.X.columns.to_numpy(dtype=str)
    reserved = set(data.reserved_test_ids)
    folds = list(make_cv(cfg).split(X, y))
    definitions = read_json(run / "cv_fold_indices.json")["folds"]
    check(X.shape == (640, 20531) and not set(ids) & reserved, "固定开发维度和测试ID隔离")
    check(read_json(run / "development_data_record.json")["strict_development_rows_only_parsed"], "仅解析开发样本数值及标签")
    expected_ranks = {}
    # 对每个公共训练折独立重新计算数值排名，但不重新训练分类器。
    for e, (train, valid) in enumerate(folds, 1):
        check(definitions[e - 1]["train_sample_ids"] == ids[train].tolist() and definitions[e - 1]["validation_sample_ids"] == ids[valid].tolist(), f"CV索引和顺序 {e}")
        with warnings.catch_warnings(), threadpool_limits(limits=1):
            warnings.simplefilter("ignore", category=UserWarning)
            warnings.simplefilter("ignore", category=RuntimeWarning)
            f, _ = f_classif(X[train], y[train])
        variance = X[train].var(axis=0, ddof=1)
        check(not np.isinf(f).any() and np.array_equal(np.isnan(f), np.ptp(X[train], axis=0) == 0), f"ANOVA未定义仅常数基因 {e}")
        expected_ranks[e] = {"variance": rank_scores(variance, "variance"), "anova": rank_scores(f, "anova")}
    configurations = [("full_svm", 20531)] + [(m, k) for k in cfg.k_values for m in METHODS]
    for method, k in configurations:
        coverage = np.zeros((20, 640), dtype=int)
        for e, (train, valid) in enumerate(folds, 1):
            record, arrays = load_checkpoint(run / "classification" / "checkpoints" / f"{method}_k{k}_{e:03d}", identity)
            row, audit = record["metrics"], record["audit"]
            coverage[(e - 1) // 5, valid] += 1
            for part, idx, prediction in (("train", train, arrays["train_pred"]), ("validation", valid, arrays["valid_pred"])):
                metric = scores(y[idx], prediction)
                for name, actual in metric.items():
                    check(np.isclose(actual, row[f"{part}_{name}"], rtol=1e-12, atol=1e-12), f"预测重算 {method}/{k}/{e}/{part}/{name}")
            check(audit["reserved_test_overlap"] == 0 and audit["train_validation_overlap"] == 0 and audit["scaler_fit_audit_passed"], f"隔离和scaler审计 {method}/{k}/{e}")
            check(audit["scaler_training_samples"] == 512 and audit["scaler_features"] == k, f"scaler范围 {method}/{k}/{e}")
            if method != "full_svm":
                selected = arrays["selected"]
                selector = "variance" if method == "variance_svm" else "anova"
                check(len(selected) == len(set(selected)) == k and np.array_equal(np.sort(expected_ranks[e][selector][:k]), selected), f"实际训练折TopK {method}/{k}/{e}")
                check(audit["selector_fit_samples"] == 512 and audit["selector_fit_calls"] == audit["scaler_fit_calls"] == audit["classifier_fit_calls"] == 1, f"三步骤fit各一次 {method}/{k}/{e}")
        check(np.all(coverage == 1), f"每轮640样本恰好一次OOF {method}/{k}")
    fold_table = pd.read_csv(run / "classification" / "cv_fold_results.csv")
    oof = pd.read_csv(run / "classification" / "oof_predictions.csv")
    summary = pd.read_csv(run / "classification" / "cv_summary.csv")
    round_table = pd.read_csv(run / "classification" / "cv_round_results.csv")
    matrix = pd.read_csv(run / "classification" / "round_confusion_matrices.csv")
    check(len(fold_table) == 1900 and len(round_table) == 380 and len(oof) == 243200, "分类总记录数1900/380/243200")
    check(not set(oof.sample_id) & reserved and set(oof.sample_id) == set(ids), "OOF未混入测试患者")
    check(fold_table.groupby(["method", "k"]).size().eq(100).all(), "19种配置每种100折")
    for (method, k), group in fold_table.groupby(["method", "k"]):
        s = summary.loc[summary.method.eq(method) & summary.k.eq(k) & summary.level.eq("validation_fold")].iloc[0]
        for metric in ("macro_f1", "balanced_accuracy", "accuracy"):
            for name, value in descriptive(group[f"validation_{metric}"]).items():
                if name != "n":
                    check(np.isclose(s[f"validation_{metric}_{name}"], value, rtol=1e-12, atol=1e-12), f"折描述统计 {method}/{k}/{metric}/{name}")
    for (method, k, repeat), group in oof.groupby(["method", "k", "repeat_id"]):
        r = round_table.loc[round_table.method.eq(method) & round_table.k.eq(k) & round_table.repeat_id.eq(repeat)].iloc[0]
        for name, value in scores(group.y_true, group.y_pred).items():
            check(np.isclose(r[f"oof_{name}"], value, rtol=1e-12, atol=1e-12), f"轮OOF重算 {method}/{k}/{repeat}/{name}")
        counts = matrix.loc[matrix.method.eq(method) & matrix.k.eq(k) & matrix.repeat_id.eq(repeat)]
        check(len(counts) == 25 and counts["count"].sum() == 640, f"轮混淆矩阵 {method}/{k}/{repeat}")
    selected_table = pd.read_csv(run / "classification" / "selected_features_by_fold.csv")
    check(len(selected_table) == 100 * 3 * sum(cfg.k_values), "逐折选中特征总行数")
    check(np.array_equal(genes[selected_table.original_column_index], selected_table.gene_id), "分类特征原始基因列名匹配")
    subsamples = list(StratifiedShuffleSplit(n_splits=30, train_size=.8, random_state=42).split(X, y))
    subindices = pd.read_csv(run / "stability" / "subsample_indices.csv")
    subfeatures = pd.read_csv(run / "stability" / "selected_features_by_subsample.csv")
    frequency = pd.read_csv(run / "stability" / "feature_selection_frequency.csv")
    pairs = pd.read_csv(run / "stability" / "stability_pairwise_jaccard.csv")
    stability = pd.read_csv(run / "stability" / "stability_summary.csv")
    cross = pd.read_csv(run / "stability" / "cross_method_jaccard.csv")
    check(len(subindices) == 30 * 512 and not set(subindices.sample_id) & reserved, "共享子采样仅512开发样本")
    check(len(subfeatures) == 30 * 3 * sum(cfg.k_values), "子采样选择记录总数")
    check(np.array_equal(genes[subfeatures.original_column_index], subfeatures.gene_id), "稳定性基因列名匹配")
    for sid, (train, omitted) in enumerate(subsamples, 1):
        r, arrays = load_checkpoint(run / "stability" / "checkpoints" / f"subsample_{sid:02d}", identity)
        group = subindices.loc[subindices.subsample_id.eq(sid)]
        check(np.array_equal(group.sample_id.to_numpy(), ids[train]), f"共享子采样索引 {sid}")
        check(np.array_equal(arrays["train_indices"], train) and np.array_equal(arrays["omitted_indices"], omitted), f"子采样断点索引 {sid}")
        check(np.allclose(arrays["svc_l2"], np.linalg.norm(arrays["coefficients"], axis=0), rtol=1e-12, atol=1e-12), f"多分类系数L2范数 {sid}")
        check(r["audit"]["scaler_fit_audit_passed"] and r["audit"]["n_samples"] == 512 and r["audit"]["reserved_test_overlap"] == 0, f"系数模型拟合审计 {sid}")
    sets = {}
    for (method, k, sid), group in subfeatures.groupby(["method", "k", "subsample_id"]):
        check(len(group) == group.gene_id.nunique() == k, f"子采样集合大小唯一性 {method}/{k}/{sid}")
        sets[(method, k, sid)] = set(group.original_column_index)
    for r in pairs.itertuples():
        a, b = sets[(r.method, r.k, r.subsample_a)], sets[(r.method, r.k, r.subsample_b)]
        intersection = len(a & b)
        check(np.isclose(r.jaccard, intersection / len(a | b), rtol=1e-12, atol=1e-12) and intersection == r.overlap, f"Jaccard逐对 {r.method}/{r.k}/{r.subsample_a}/{r.subsample_b}")
    for (method, k), group in pairs.groupby(["method", "k"]):
        check(len(group) == 435 and len(set(zip(group.subsample_a, group.subsample_b))) == 435, f"全部435无序对 {method}/{k}")
        s = stability.loc[stability.method.eq(method) & stability.k.eq(k)].iloc[0]
        for name, value in descriptive(group.jaccard).items():
            if name != "n":
                check(np.isclose(s[f"jaccard_{name}"], value, rtol=1e-12, atol=1e-12), f"稳定性汇总 {method}/{k}/{name}")
        counts = np.zeros(20531, dtype=int)
        for sid in range(1, 31):
            counts[list(sets[(method, k, sid)])] += 1
        freq = frequency.loc[frequency.method.eq(method) & frequency.k.eq(k)].sort_values("original_column_index")
        check(len(freq) == 20531 and np.array_equal(freq.selection_count.to_numpy(), counts), f"全部基因频率 {method}/{k}")
    for r in cross.itertuples():
        a, b = sets[(r.method_a, r.k, r.subsample_id)], sets[(r.method_b, r.k, r.subsample_id)]
        check(np.isclose(r.jaccard, len(a & b) / len(a | b), rtol=1e-12, atol=1e-12), f"同子采样跨方法 {r.method_a}/{r.method_b}/{r.k}/{r.subsample_id}")
    joint = pd.read_csv(run / "analysis" / "performance_stability_summary.csv")
    check(len(joint) == 18 and not joint.selector.eq("svc_l2").any(), "RQ3未错误配对系数稳定性与其他分类分数")
    candidates = pd.read_csv(run / "analysis" / "candidate_k_selection.csv")
    check(candidates.delta.eq(.005).all(), "候选K容忍规则未事后更改")
    for method, group in candidates.groupby("method"):
        valid = group.loc[group.qualifies, "k"]
        marked = group.loc[group.is_minimal_candidate_within_prelisted_grid, "k"]
        check((len(valid) == len(marked) == 0) or (len(marked) == 1 and marked.iloc[0] == valid.min()), f"候选K确为预列集合最小 {method}")
    pngs, pdfs = sorted((run / "figures").glob("*.png")), sorted((run / "figures").glob("*.pdf"))
    check(len(pngs) == len(pdfs) == 7, "七张PNG及七份PDF")
    for png in pngs:
        with Image.open(png) as picture:
            picture.verify()
        with Image.open(png) as picture:
            check(min(picture.info.get("dpi", (0, 0))) >= 300, f"图片分辨率 {png.name}")
        check(png.with_suffix(".pdf").read_bytes().startswith(b"%PDF"), f"矢量PDF {png.name}")
    result = {"status": "passed", "checks_passed": len(checks), "checks": checks,
              "classifier_models_refitted_during_verification": 0,
              "verification_independently_recomputes_fold_rankings_without_model_fit": True,
              "reserved_test_accessed": False, "visual_layout_review": "separate manual review of exported PNG previews"}
    atomic_json(run / "analysis" / "verification.json", result)
    return result
