# -*- coding: utf-8 -*-
"""从真实逐折断点聚合结果；不调用模型 fit，不访问保留测试数据。"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from ablation_engine import METHODS, METRICS, atomic_json, load_checkpoint, read_json, scores
from config import CLASS_ORDER
from repeated_cv import descriptive


def save(frame, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def class_metrics(true, predicted, common):
    precision, recall, f1, support = precision_recall_fscore_support(true, predicted, labels=list(CLASS_ORDER), zero_division=0)
    return [{**common, "cancer_type": c, "precision": float(p), "recall": float(r), "f1": float(f), "support": int(n)}
            for c, p, r, f, n in zip(CLASS_ORDER, precision, recall, f1, support)]


def aggregate_classification(run, data, cfg, identity, require_complete):
    """每个 K 完成后重建累计 CSV；未完成的配置不会被混入完整配置统计。"""
    output = run / "classification"
    folds = read_json(run / "cv_fold_indices.json")["folds"]
    details, audit, oof_parts, per_class, warnings = [], [], [], [], []
    feature_path = output / "selected_features_by_fold.csv"
    temporary_features = feature_path.with_suffix(".tmp.csv")
    feature_header = True
    completed = []
    for method, k in [("full_svm", 20531)] + [(m, k) for k in cfg.k_values for m in METHODS]:
        paths = [output / "checkpoints" / f"{method}_k{k}_{e:03d}" for e in range(1, 101)]
        if not all(p.with_suffix(".json").exists() for p in paths):
            if require_complete:
                raise ValueError(f"缺少 {method} K={k} 的正式折记录")
            continue
        completed.append((method, k))
        for e, path in enumerate(paths, 1):
            record, arrays = load_checkpoint(path, identity)
            row = record["metrics"]
            definition = folds[e - 1]
            assert (row["evaluation_id"], row["repeat_id"], row["fold_id"]) == (e, definition["repeat"], definition["fold"])
            valid_ids, train_ids = definition["validation_sample_ids"], definition["train_sample_ids"]
            vp, tp = arrays["valid_pred"], arrays["train_pred"]
            assert len(vp) == len(valid_ids) == 128 and len(tp) == len(train_ids) == 512
            for part, truths, pred in (("train", data.y.loc[train_ids], tp), ("validation", data.y.loc[valid_ids], vp)):
                for metric, value in scores(truths, pred).items():
                    np.testing.assert_allclose(row[f"{part}_{metric}"], value, rtol=1e-12, atol=1e-12)
            details.append(row)
            audit.append(record["audit"])
            warnings.extend({"method": method, "k": k, "evaluation_id": e, **w} for w in record["warnings"])
            common = {"method": method, "k": k, "evaluation_id": e, "repeat_id": row["repeat_id"], "fold_id": row["fold_id"]}
            oof = pd.DataFrame({**common, "sample_id": valid_ids, "y_true": data.y.loc[valid_ids].to_numpy(), "y_pred": vp})
            oof["is_error"] = oof.y_true.ne(oof.y_pred)
            oof_parts.append(oof)
            per_class.extend(class_metrics(oof.y_true, oof.y_pred, {**common, "level": "validation_fold"}))
            if method != "full_svm":
                selected = arrays["selected"]
                assert len(selected) == len(set(selected)) == k
                f = pd.DataFrame({**common, "gene_id": data.X.columns[selected], "original_column_index": selected,
                                  "transform_position": np.arange(k) + 1,
                                  **{key: arrays[key] for key in ("selection_rank", "selector_score", "training_variance", "training_anova_f_score")}})
                f.to_csv(temporary_features, mode="w" if feature_header else "a", header=feature_header, index=False,
                         encoding="utf-8-sig" if feature_header else "utf-8")
                feature_header = False
    if not feature_header:
        temporary_features.replace(feature_path)
    fold_table = pd.DataFrame(details)
    oof = pd.concat(oof_parts, ignore_index=True)
    rounds, matrices = [], []
    for (method, k, repeat), group in oof.groupby(["method", "k", "repeat_id"], sort=False):
        assert len(group) == group.sample_id.nunique() == 640 and set(group.sample_id) == set(data.X.index)
        common = {"method": method, "k": int(k), "repeat_id": int(repeat)}
        fold_rows = fold_table.loc[fold_table.method.eq(method) & fold_table.k.eq(k) & fold_table.repeat_id.eq(repeat)]
        assert len(fold_rows) == 5
        rounds.append({**common, **{f"oof_{name}": value for name, value in scores(group.y_true, group.y_pred).items()},
                       "oof_error_count": int(group.is_error.sum()), "fit_seconds_sum": float(fold_rows.fit_seconds.sum()),
                       **{f"{col}_mean": float(fold_rows[col].mean()) for col in fold_rows if col.startswith(("train_", "validation_", "gap_"))}})
        per_class.extend(class_metrics(group.y_true, group.y_pred, {**common, "evaluation_id": 0, "fold_id": 0, "level": "round_oof"}))
        matrix = confusion_matrix(group.y_true, group.y_pred, labels=list(CLASS_ORDER))
        matrices.extend({**common, "true_label": c, "predicted_label": d, "count": int(matrix[i, j])}
                        for i, c in enumerate(CLASS_ORDER) for j, d in enumerate(CLASS_ORDER))
    round_table = pd.DataFrame(rounds)
    summaries = []
    for (method, k), group in fold_table.groupby(["method", "k"], sort=False):
        round_group = round_table.loc[round_table.method.eq(method) & round_table.k.eq(k)]
        for level, table, columns in (("validation_fold", group, [c for c in group if c.startswith(("train_", "validation_", "gap_"))] + ["fit_seconds", "predict_seconds"]),
                                      ("round_oof", round_group, ["oof_macro_f1", "oof_balanced_accuracy", "oof_accuracy", "oof_error_count", "fit_seconds_sum"])):
            row = {"method": method, "k": int(k), "level": level, "n": len(table)}
            for column in columns:
                row.update({f"{column}_{stat}": value for stat, value in descriptive(table[column]).items() if stat != "n"})
            summaries.append(row)
    sample_errors = oof.groupby(["method", "k", "sample_id", "y_true"], sort=False).is_error.agg(error_count="sum", n_predictions="size").reset_index()
    sample_errors["error_rate"] = sample_errors.error_count / sample_errors.n_predictions
    assert sample_errors.n_predictions.eq(20).all()
    paired = []
    for k in cfg.k_values:
        for a, b in itertools.combinations(METHODS, 2):
            left = fold_table.loc[fold_table.method.eq(a) & fold_table.k.eq(k)]
            right = fold_table.loc[fold_table.method.eq(b) & fold_table.k.eq(k)]
            if len(left) == len(right) == 100:
                paired_group = left.merge(right, on=["evaluation_id", "repeat_id", "fold_id"], suffixes=("_a", "_b"), validate="one_to_one")
                for r in paired_group.itertuples():
                    paired.append({"method_a": a, "method_b": b, "k": k, "evaluation_id": r.evaluation_id,
                                   **{f"delta_{m}_a_minus_b": getattr(r, f"validation_{m}_a") - getattr(r, f"validation_{m}_b") for m in METRICS}})
    for name, table in (("cv_fold_results.csv", fold_table), ("cv_round_results.csv", round_table), ("cv_summary.csv", pd.DataFrame(summaries)),
                        ("model_fit_audit.csv", pd.DataFrame(audit)), ("oof_predictions.csv", oof), ("per_class_results.csv", pd.DataFrame(per_class)),
                        ("round_confusion_matrices.csv", pd.DataFrame(matrices)), ("sample_error_frequency.csv", sample_errors),
                        ("error_predictions.csv", oof.loc[oof.is_error]), ("paired_method_differences.csv", pd.DataFrame(paired)),
                        ("warnings.csv", pd.DataFrame(warnings, columns=["method", "k", "evaluation_id", "category", "message"]))):
        save(table, output / name)
    atomic_json(output / "aggregation_status.json", {"completed_configurations": [{"method": m, "k": k} for m, k in completed],
                "expected_configurations": 19, "n_fold_results": len(fold_table), "full_baseline_features": "all original columns in gene_catalog.csv; no selection",
                "full_baseline_gene_list_per_fold": "gene_catalog.csv, identical all 100 folds", "training_predictions": "complete per-fold arrays in checkpoints/*.npz"})
    return fold_table


def make_joint_report(run, cfg):
    """联合分析与文字报告在 RQ1/RQ2 全部完成后生成。"""
    from ablation_report import build_report
    return build_report(run, cfg)
