# -*- coding: utf-8 -*-
"""无分类器重训的融合实验验收；独立核对集合、预测、配对和子采样。"""
from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.feature_selection import f_classif

from ablation_engine import METRICS, atomic_json, load_checkpoint, read_json
from config import CLASS_ORDER
from cross_validation import make_cv
from fusion_selection import schemes, training_digest
from repeated_cv import descriptive


def scores(truth, prediction):
    """独立按混淆计数重算指标，避免重复调用三次scikit-learn校验开销。"""
    labels = np.sort(np.asarray(CLASS_ORDER, dtype=str))
    a, b = np.asarray(truth, dtype=str), np.asarray(prediction, dtype=str)
    ia, ib = np.searchsorted(labels, a), np.searchsorted(labels, b)
    if not np.array_equal(labels[ia], a) or not np.array_equal(labels[ib], b):
        raise ValueError("预测或真实标签不在五癌种定义中")
    matrix = np.bincount(ia * 5 + ib, minlength=25).reshape(5, 5)
    true, predicted, tp = matrix.sum(axis=1), matrix.sum(axis=0), np.diag(matrix)
    f1 = np.divide(2 * tp, true + predicted, out=np.zeros(5, float), where=(true + predicted) > 0)
    recall = np.divide(tp, true, out=np.zeros(5, float), where=true > 0)
    return {"macro_f1": float(f1.mean()), "balanced_accuracy": float(recall[true > 0].mean()),
            "accuracy": float(tp.sum() / len(a))}


def reference_selection(a, b, s):
    """独立集合构造，避免只验证集合长度而遗漏配额、补充和匹配M规则。"""
    A, B = set(map(int, a[:s.k])), set(map(int, b[:s.k]))
    if s.rule == "anova":
        return A
    if s.rule == "variance":
        return B
    if s.rule == "intersection":
        return A.intersection(B)
    if s.rule == "union":
        return A.union(B)
    if s.rule == "anova_only":
        return A.difference(B)
    if s.rule == "variance_only":
        return B.difference(A)
    if s.rule == "anova_matched_union":
        return set(map(int, a[:len(A | B)]))
    if s.rule == "variance_matched_union":
        return set(map(int, b[:len(A | B)]))
    if s.rule == "add_variance":
        primary, secondary, nmain, total = a, b, 50, 50+s.increment
    else:
        primary, secondary = (b, a) if s.rule == "fusion_variance75" else (a, b)
        ratio = .5 if s.rule == "fusion_equal" else .75
        nmain, total = int(np.floor(s.k * ratio + .5)), s.k
    selected = set(map(int, primary[:nmain]))
    for gene in secondary:
        if len(selected) == total:
            break
        selected.add(int(gene))
    return selected


def verify(run, data, cfg, identity):
    checks = []
    def check(condition, message):
        if not bool(condition):
            raise AssertionError(message)
        checks.append(message)
    X, y, ids = data.X.to_numpy(dtype=float), data.y.to_numpy(dtype=str), data.X.index.to_numpy(dtype=str)
    reserve = set(data.reserved_test_ids)
    check(X.shape == (640, 20531) and not set(ids) & reserve, "开发集维度与测试ID隔离")
    check(read_json(run / "development_data_record.json")["strict_development_rows_only_parsed"], "仅开发行表达与标签被解析")
    definitions = read_json(run / "cv_fold_indices.json")["folds"]
    actual_folds = list(make_cv(cfg).split(X, y))
    ranks = {}
    for e, (train, valid) in enumerate(actual_folds, 1):
        definition = definitions[e-1]
        check(ids[train].tolist() == definition["train_sample_ids"] and ids[valid].tolist() == definition["validation_sample_ids"], f"同一CV索引及顺序 {e}")
        record, arrays = load_checkpoint(run / "scores_cv" / f"fold_{e:03d}", identity)
        check(record["sample_ids"] == ids[train].tolist() and record["training_digest"] == training_digest(X[train], y[train]), f"评分缓存绑定当前训练范围 {e}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            warnings.simplefilter("ignore", category=RuntimeWarning)
            f, _ = f_classif(X[train], y[train])
        variance = X[train].var(axis=0, ddof=1)
        np.testing.assert_allclose(f, arrays["anova"], rtol=1e-10, atol=1e-10, equal_nan=True)
        np.testing.assert_allclose(variance, arrays["variance"], rtol=1e-12, atol=1e-12)
        a = np.argsort(np.where(np.isnan(f), -np.inf, f), kind="stable")[::-1]
        b = np.argsort(-variance, kind="stable")
        check(np.array_equal(a, arrays["anova_rank"]) and np.array_equal(b, arrays["variance_rank"]), f"重新计算折内两种排名 {e}")
        ranks[e] = a, b
    for s in schemes():
        coverage = np.zeros((20, 640), int)
        for e, (train, valid) in enumerate(actual_folds, 1):
            record, arrays = load_checkpoint(run / "checkpoints" / f"{s.name}_{e:03d}", identity)
            row, audit = record["metrics"], record["audit"]
            expected = reference_selection(*ranks[e], s)
            check(set(arrays["selected"]) == expected and len(arrays["selected"]) == len(expected), f"独立集合规则 {s.name}/{e}")
            check(row["n_features"] == len(expected) and row["scheme"] == s.name and row["evaluation_id"] == e, f"实际特征数与任务标识 {s.name}/{e}")
            check(audit["reserved_test_overlap"] == 0 and audit["train_validation_overlap"] == 0, f"拟合ID隔离 {s.name}/{e}")
            if not expected:
                check(row["status"] == "skipped_empty" and audit["classifier_fit_calls"] == 0 and len(arrays["valid_pred"]) == 0, f"空集合明确跳过 {s.name}/{e}")
                continue
            coverage[(e-1)//5, valid] += 1
            check(audit["scaler_fit_audit_passed"] and audit["scaler_training_samples"] == 512 and audit["scaler_features"] == len(expected), f"标准化器训练范围 {s.name}/{e}")
            for part, index, prediction in (("train", train, arrays["train_pred"]), ("validation", valid, arrays["valid_pred"])):
                for metric, value in scores(y[index], prediction).items():
                    check(np.isclose(row[f"{part}_{metric}"], value, rtol=1e-12, atol=1e-12), f"真实预测指标 {s.name}/{e}/{part}/{metric}")
        check(np.all(coverage <= 1), f"每轮每开发患者至多一次OOF {s.name}")
    fold = pd.read_csv(run / "fusion_cv_fold_results.csv")
    summary = pd.read_csv(run / "fusion_cv_summary.csv")
    rounds = pd.read_csv(run / "fusion_cv_round_results.csv")
    oof = pd.read_csv(run / "fusion_oof_predictions.csv")
    check(len(fold) == 3100 and len(rounds) == 620 and len(summary) == 31, "31方案完整3100折及620轮记录")
    check(not set(oof.sample_id) & reserve, "OOF排除保留患者")
    for scheme, group in fold.groupby("scheme"):
        s = summary.loc[summary.scheme.eq(scheme)].iloc[0]
        evaluated = group.loc[group.status.eq("evaluated")]
        check(len(group) == 100 and s.n_evaluated_folds == len(evaluated), f"未静默丢弃折 {scheme}")
        for m in METRICS:
            if len(evaluated):
                for key, value in descriptive(evaluated[f"validation_{m}"]).items():
                    if key != "n":
                        check(np.isclose(s[f"validation_{m}_{key}"], value, rtol=1e-12, atol=1e-12), f"折汇总 {scheme}/{m}/{key}")
    for r in rounds.itertuples():
        group = oof.loc[oof.scheme.eq(r.scheme) & oof.repeat_id.eq(r.repeat_id)]
        complete = len(group) == group.sample_id.nunique() == 640
        check(complete == (r.status == "complete"), f"轮完整性 {r.scheme}/{r.repeat_id}")
        if complete:
            for metric, value in scores(group.y_true, group.y_pred).items():
                check(np.isclose(getattr(r, f"oof_{metric}"), value, rtol=1e-12, atol=1e-12), f"轮OOF指标 {r.scheme}/{r.repeat_id}/{metric}")
    features = pd.read_csv(run / "fusion_selected_features.csv")
    check(np.array_equal(data.X.columns[features.original_column_index], features.gene_id), "全部基因名称对应原始表达列")
    for e in range(1, 101):
        for k in (20, 50):
            union = fold.loc[fold.scheme.eq(f"union_k{k}") & fold.evaluation_id.eq(e)].n_features.iloc[0]
            for method in ("anova", "variance"):
                n = fold.loc[fold.scheme.eq(f"{method}_matched_union_k{k}") & fold.evaluation_id.eq(e)].n_features.iloc[0]
                check(n == union, f"同折并集M数量匹配 {method}/{k}/{e}")
    parent = read_json(run / "logs" / "reuse_audit.json")["source_directory"]
    from pathlib import Path
    old_indices = pd.read_csv(Path(parent) / "stability" / "subsample_indices.csv")
    new_indices = pd.read_csv(run / "stability" / "subsample_indices.csv")
    check(old_indices.equals(new_indices), "精确复用原30组子采样索引")
    sets = {}
    selected_schemes = [s for s in schemes() if s.experiment in ("A", "B")]
    for sid, group in new_indices.groupby("subsample_id"):
        group = group.sort_values("sample_position_in_subsample")
        names = group.sample_id.tolist()
        r, arrays = load_checkpoint(run / "scores_subsamples" / f"subsample_{sid:02d}", identity)
        check(len(names) == len(set(names)) == 512 and not set(names) & reserve, f"子采样范围 {sid}")
        check(r["training_digest"] == training_digest(data.X.loc[names].to_numpy(dtype=float), data.y.loc[names].to_numpy(dtype=str)), f"子采样评分范围 {sid}")
        for s in selected_schemes:
            sets[(s.name, sid)] = reference_selection(arrays["anova_rank"], arrays["variance_rank"], s)
    pairs = pd.read_csv(run / "stability" / "pairwise_jaccard.csv")
    stability = pd.read_csv(run / "fusion_feature_stability.csv")
    freq = pd.read_csv(run / "fusion_feature_frequency.csv")
    for r in pairs.itertuples():
        a, b = sets[(r.scheme, r.subsample_a)], sets[(r.scheme, r.subsample_b)]
        expected = len(a & b) / len(a | b) if a | b else np.nan
        check((np.isnan(expected) and np.isnan(r.jaccard)) or np.isclose(expected, r.jaccard, rtol=1e-12, atol=1e-12), f"稳定性逐对Jaccard {r.scheme}/{r.subsample_a}/{r.subsample_b}")
    for s in selected_schemes:
        group = pairs.loc[pairs.scheme.eq(s.name)]
        check(len(group) == 435 and len(set(zip(group.subsample_a, group.subsample_b))) == 435, f"435个不同无序对 {s.name}")
        counts = np.zeros(20531, int)
        for sid in range(1, 31):
            counts[list(sets[(s.name, sid)])] += 1
        g = freq.loc[freq.scheme.eq(s.name)].sort_values("original_column_index")
        check(len(g) == 20531 and np.array_equal(counts, g.selection_count), f"完整基因入选频率 {s.name}")
        st = stability.loc[stability.scheme.eq(s.name)].iloc[0]
        if group.jaccard.notna().any():
            for key, value in descriptive(group.jaccard.dropna()).items():
                if key != "n":
                    check(np.isclose(st[f"jaccard_{key}"], value, rtol=1e-12, atol=1e-12), f"稳定性汇总 {s.name}/{key}")
    paired = pd.read_csv(run / "fusion_paired_fold_differences.csv")
    for (target, reference), group in paired.groupby(["target", "reference"]):
        a, b = fold.loc[fold.scheme.eq(target)].set_index("evaluation_id"), fold.loc[fold.scheme.eq(reference)].set_index("evaluation_id")
        for metric in METRICS:
            expected = a.loc[group.evaluation_id, f"validation_{metric}"].to_numpy() - b.loc[group.evaluation_id, f"validation_{metric}"].to_numpy()
            check(np.allclose(group[f"delta_{metric}"], expected, rtol=1e-12, atol=1e-12), f"同折性能差 {target}/{reference}/{metric}")
    transition = pd.read_csv(run / "fusion_prediction_transitions.csv")
    indexed = oof.set_index(["scheme", "evaluation_id", "sample_id"])
    check(indexed.index.is_unique, "OOF配置/验证折/患者键唯一")
    for r in transition.itertuples():
        target = indexed.loc[(r.target, r.evaluation_id, r.sample_id)]
        baseline = indexed.loc[(r.reference, r.evaluation_id, r.sample_id)]
        expected = "rescued" if baseline.is_error and not target.is_error else "new_error" if not baseline.is_error and target.is_error else "unchanged"
        check(expected == r.change and target.y_pred == r.target_prediction and baseline.y_pred == r.reference_prediction, f"患者预测变化 {r.target}/{r.reference}/{r.evaluation_id}/{r.sample_id}")
    for extension in ("png", "pdf"):
        files = list((run / "figures").glob(f"*.{extension}"))
        check(len(files) == 7, f"七份{extension}图表")
        for f in files:
            if extension == "png":
                with Image.open(f) as picture:
                    check(min(picture.info.get("dpi", (0, 0))) >= 330-.1, f"330DPI {f.name}")
                    picture.verify()
            else:
                check(f.read_bytes().startswith(b"%PDF"), f"有效矢量PDF {f.name}")
    result = {"status": "passed", "checks_passed": len(checks), "checks": checks, "classifier_refits_during_verification": 0,
              "reserved_test_used": False, "independent_sample_tests_performed": False}
    atomic_json(run / "verification.json", result)
    return result
