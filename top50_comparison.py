# -*- coding: utf-8 -*-
"""固定K=50和C=1的配对重复CV；每个训练折重新选择，绝不读取EDA基因名单。"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits

from baseline import build_baseline
from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from cross_validation import _audit_fold_pipeline, frozen_pipeline_record, make_cv
from data_loader import load_existing_development_data, write_json
from evaluation import compute_metrics
from feature_selection import build_anova_pipeline
from variance_topk import VarianceTopK

METHODS = ("variance_top50_svm", "anova_top50_svm")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_comparison_pipelines(cfg):
    """复用已有ANOVA Pipeline；A只替换选择器，其他设置完全一致。"""
    anova = build_anova_pipeline(cfg, k=50, classifier="linear_svm", C=1.0)
    variance = clone(anova).set_params(select=VarianceTopK(k=50))
    return {METHODS[0]: variance, METHODS[1]: anova}


def training_statistics(X, y):
    """从训练折原表达值独立计算方差和ANOVA均方比，用于泄漏审计。"""
    a = X.to_numpy(dtype=float)
    mean = a.mean(axis=0)
    variance = a.var(axis=0, ddof=1)
    constant = np.ptp(a, axis=0) == 0
    between, within = np.zeros(a.shape[1]), np.zeros(a.shape[1])
    for label in CLASS_ORDER:
        group = a[y.eq(label).to_numpy()]
        mu = group.mean(axis=0)
        between += len(group) * (mu - mean) ** 2
        within += ((group - mu) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = (between / 4) / (within / (len(X) - 5))
    f[constant] = np.nan
    return variance, f, constant


def confirm_baseline(cfg, data, folds, output):
    """先核对既有基线，只有所有数据及100折ID完全一致才允许配对。"""
    pointer = read_json(cfg.output_dir / "latest_repeated_cv.json")
    parent = cfg.output_dir / pointer["run_directory"]
    original = read_json(parent / "config.json")
    previous_folds = read_json(parent / "cv_fold_indices.json")["folds"]
    checks = {
        "prior_run_complete": pointer["status"] == "complete" and read_json(parent / "stage_status.json")["status"] == "complete",
        "manifest_identical_including_sample_order": read_json(cfg.split_manifest_path) == read_json(parent / "split_manifest.json"),
        "development_values_and_labels_fingerprint_identical": read_json(output / "development_data_record.json")["development_fingerprint_sha256"] == read_json(parent / "development_data_record.json")["development_fingerprint_sha256"],
        "all_100_fold_ids_and_order_identical": previous_folds == folds,
        "pipeline_identical_except_feature_selector": frozen_pipeline_record(build_baseline(cfg), "full_linear_svm", "none", "all") == read_json(parent / "frozen_pipeline.json"),
        "cv_configuration_identical": all(cfg.to_dict()[k] == original[k] for k in ("random_state", "n_splits", "n_repeats", "cv_mode")),
        "original_not_label_permuted": not original["label_permutation_enabled"],
    }
    prior_oof = pd.read_csv(parent / "repeated_cv_oof_predictions.csv")
    labels = prior_oof.loc[prior_oof["round"].eq(1)].set_index("sample_id").y_true
    checks["development_label_mapping_identical"] = set(labels.index) == set(data.y.index) and np.array_equal(labels.loc[data.y.index].to_numpy(), data.y.to_numpy())
    record = {"source_directory": str(parent.relative_to(cfg.output_dir)), "checks": checks,
              "paired_baseline_comparison_allowed": all(checks.values()), "baseline_refitted": False}
    write_json(output / "baseline_identity_audit.json", record)
    return parent, record


def fit_one(method, estimator, Xtrain, ytrain, Xvalid, yvalid, variance, manual_f, constant,
            evaluation_id, cfg, reserved_ids):
    """每次克隆未拟合Pipeline；追踪三个fit调用及实际输入，保存真实选中基因。"""
    fitted = clone(estimator)
    selector, scaler, model = (fitted.named_steps[k] for k in ("select", "scale", "model"))
    if any(hasattr(obj, attr) for obj, attr in ((selector, "n_features_in_"), (scaler, "mean_"), (model, "coef_"))):
        raise AssertionError("Pipeline没有从未拟合状态开始")
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg.numeric_threads):
        warnings.simplefilter("always")
        with patch.object(selector, "fit", wraps=selector.fit) as selection_fit, \
             patch.object(scaler, "fit", wraps=scaler.fit) as scaler_fit, \
             patch.object(model, "fit", wraps=model.fit) as classifier_fit:
            start = time.perf_counter()
            fitted.fit(Xtrain, ytrain)
            fit_seconds = time.perf_counter() - start
            if (selection_fit.call_count, scaler_fit.call_count, classifier_fit.call_count) != (1, 1, 1):
                raise AssertionError("每个Pipeline步骤的fit调用次数异常")
            selection_X, selection_y = selection_fit.call_args.args[:2]
            scale_X = scaler_fit.call_args.args[0]
            model_X, model_y = classifier_fit.call_args.args[:2]
            if not isinstance(selection_X, pd.DataFrame) or selection_X.index.tolist() != Xtrain.index.tolist():
                raise AssertionError("选择器fit输入不是当前训练折")
            np.testing.assert_array_equal(selection_X.to_numpy(), Xtrain.to_numpy())
            np.testing.assert_array_equal(selection_y, ytrain)
            np.testing.assert_array_equal(model_y, ytrain)
        start = time.perf_counter()
        train_pred, valid_pred = fitted.predict(Xtrain), fitted.predict(Xvalid)
        predict_seconds = time.perf_counter() - start
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        raise RuntimeError(f"{method}第{evaluation_id}次未收敛，停止，不更换C或隐瞒警告")
    support = selector.get_support()
    if selector.n_features_in_ != 20531 or support.sum() != 50:
        raise AssertionError("选择器输入维度或实际选择数量异常")
    if method == METHODS[0]:
        scores = selector.variances_
        np.testing.assert_allclose(scores, variance, rtol=1e-12, atol=1e-12)
        ranked = np.argsort(-scores, kind="stable")
        if selector.n_samples_seen_ != 512:
            raise AssertionError("方差选择器使用的样本数不是512")
    else:
        scores = selector.scores_
        if np.any(np.isnan(scores) & ~constant) or np.isinf(scores).any() or np.any(scores[np.isfinite(scores)] < 0):
            raise ValueError("ANOVA存在非恒定基因NaN、无穷值或负分数，已停止诊断")
        if not np.isnan(scores[constant]).all():
            raise ValueError("恒定基因ANOVA分数异常")
        np.testing.assert_allclose(scores[~constant], manual_f[~constant], rtol=1e-6, atol=1e-6)
        # 与原版SelectKBest完全相同：稳定升序取最后K个；边界并列偏向原列号较大者。
        ranked = np.argsort(np.where(np.isnan(scores), -np.inf, scores), kind="mergesort")[::-1]
    expected = np.zeros(20531, dtype=bool)
    expected[ranked[:50]] = True
    np.testing.assert_array_equal(support, expected)
    if not np.isfinite(scores[support]).all() or constant[support].any():
        raise ValueError("选中的Top50存在非有限评分或恒定基因")
    raw_selected = Xtrain.to_numpy()[:, support]
    np.testing.assert_array_equal(scale_X, raw_selected)
    np.testing.assert_allclose(model_X, scaler.transform(raw_selected), rtol=1e-12, atol=1e-12)
    audit = _audit_fold_pipeline(fitted, Xtrain)
    if model.n_features_in_ != 50 or not np.isfinite(model.coef_).all():
        raise AssertionError("分类器未实际使用50个有限特征")
    overlap = len(set(Xtrain.index) & set(Xvalid.index))
    reserved_overlap = len((set(Xtrain.index) | set(Xvalid.index)) & reserved_ids)
    if overlap or reserved_overlap:
        raise AssertionError("样本隔离审计失败")
    round_id, fold_id = (evaluation_id - 1) // 5 + 1, (evaluation_id - 1) % 5 + 1
    base = {"method": method, "evaluation_id": evaluation_id, "round": round_id, "fold": fold_id}
    row = {**base, "k": 50, "C": 1.0, "cv_mode": "repeated", "n_train": 512, "n_validation": 128,
           "n_features_input": 20531, "n_features_model": 50, "fit_seconds": fit_seconds,
           "predict_seconds": predict_seconds, "max_solver_iterations": int(np.max(np.atleast_1d(model.n_iter_)))}
    train_metrics, val_metrics = compute_metrics(ytrain, train_pred), compute_metrics(yvalid, valid_pred)
    for metric in train_metrics:
        row[f"train_{metric}"] = train_metrics[metric]
        row[f"validation_{metric}"] = val_metrics[metric]
        row[f"gap_{metric}"] = train_metrics[metric] - val_metrics[metric]
    audit.update(base, train_validation_overlap=overlap, reserved_test_overlap=reserved_overlap,
                 pipeline_unfitted_before_fit=True, selector_fit_calls=1, scaler_fit_calls=1, classifier_fit_calls=1,
                 selector_fit_samples=len(selection_X), selector_fit_features=selection_X.shape[1],
                 selector_fit_ids_identical_to_training=True, selector_training_scores_audit_passed=True,
                 scaler_input_is_original_selected_expression=True, classifier_input_is_training_scaled=True,
                 model_features_in=50, model_C=float(model.C), model_dual=model.dual,
                 n_constant_training_genes=int(constant.sum()), n_undefined_selector_scores=int(np.isnan(scores).sum()),
                 n_infinite_selector_scores=int(np.isinf(scores).sum()), all_selected_scores_finite=True)
    positions = np.flatnonzero(support)
    rank_map = {int(index): rank + 1 for rank, index in enumerate(ranked[:50])}
    selected = [{**base, "gene_id": Xtrain.columns[index], "original_column_index": int(index),
                 "transform_position": i + 1, "selection_rank": rank_map[int(index)],
                 "selector_score": float(scores[index]), "training_variance": float(variance[index]),
                 "training_anova_f_score": float(manual_f[index])}
                for i, index in enumerate(positions)]
    oof = [{**base, "sample_id": sid, "y_true": str(true), "y_pred": str(pred), "is_error": bool(true != pred)}
           for sid, true, pred in zip(Xvalid.index, yvalid, valid_pred)]
    training = [{**base, "sample_id": sid, "y_true": str(true), "y_pred": str(pred)}
                for sid, true, pred in zip(Xtrain.index, ytrain, train_pred)]
    warning_rows = [{**base, "category": w.category.__name__, "message": str(w.message)} for w in caught]
    return row, audit, selected, oof, training, warning_rows, np.asarray(scores).copy()


def run(cfg):
    if (cfg.cv_mode, cfg.n_splits, cfg.n_repeats, cfg.random_state, cfg.baseline_c) != ("repeated", 5, 20, 42, 1.0):
        raise ValueError("此实验固定5×20、seed=42、K=50、C=1")
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    output = cfg.output_dir / "top50_comparison" / stamp
    output.mkdir(parents=True, exist_ok=False)
    from main import environment_record
    write_json(output / "environment.json", environment_record())
    write_json(output / "config.json", {**cfg.to_dict(), "experiment_k": 50,
                                        "feature_selection_scope": "training_fold_only",
                                        "no_eda_feature_lists_read": True, "new_classifier_fits_planned": 200})
    status = {"status": "running", "new_classifier_fits_completed": 0, "test_evaluation_performed": False,
              "other_k_experiments_started": False, "hyperparameter_search_performed": False,
              "rq2_subsampling_started": False, "full_feature_baseline_refitted": False}
    write_json(output / "stage_status.json", status)
    manifest_sha = hashlib.sha256(cfg.split_manifest_path.read_bytes()).hexdigest()
    source_dir = output / "source_snapshot"
    source_dir.mkdir()
    for file in PROJECT_DIR.glob("*.py"):
        (source_dir / file.name).write_bytes(file.read_bytes())
    start = time.perf_counter()
    log = (output / "experiment.log").open("w", encoding="utf-8", buffering=1)

    def report(message):
        print(message, flush=True)
        log.write(message + "\n")

    details, audits, features, predictions, training_predictions, warning_rows = [], [], [], [], [], []
    score_arrays = {}

    def checkpoint():
        for rows, name in ((details, "top50_comparison_fold_results"), (audits, "top50_cv_fit_audit"),
                           (features, "top50_selected_features_by_fold"), (predictions, "top50_oof_predictions"),
                           (training_predictions, "top50_training_predictions")):
            pd.DataFrame(rows).to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
        write_json(output / "warnings.json", {"warnings": warning_rows})
        write_json(output / "cv_progress.json", {"completed_model_fits": len(details),
                                                  "completed_paired_splits": len(details) // 2, "planned_model_fits": 200})

    try:
        report("读取固定640个开发样本；仅解析开发行，不解析161个保留行的表达值或标签。")
        data = load_existing_development_data(cfg, output, strict_rows_only=True)
        splits = list(make_cv(cfg).split(data.X, data.y))
        folds = [{"evaluation_id": i, "repeat": (i - 1) // 5 + 1, "fold": (i - 1) % 5 + 1,
                  "train_sample_ids": data.X.index[train].tolist(), "validation_sample_ids": data.X.index[valid].tolist()}
                 for i, (train, valid) in enumerate(splits, 1)]
        write_json(output / "cv_fold_indices.json", {"cv_mode": "repeated", "folds": folds})
        parent, identity = confirm_baseline(cfg, data, folds, output)
        report(f"原全特征基线逐折配对资格：{identity['paired_baseline_comparison_allowed']}；不重新拟合基线。")
        pipelines = build_comparison_pipelines(cfg)
        write_json(output / "frozen_pipelines.json", {m: frozen_pipeline_record(p, m, m.split('_')[0], 50) for m, p in pipelines.items()})
        for evaluation_id, (train, valid) in enumerate(splits, 1):
            Xtrain, ytrain = data.X.iloc[train], data.y.iloc[train]
            Xvalid, yvalid = data.X.iloc[valid], data.y.iloc[valid]
            variance, manual_f, constant = training_statistics(Xtrain, ytrain)
            for method, pipeline in pipelines.items():
                row, audit, selected, oof, tr, caught, scores = fit_one(
                    method, pipeline, Xtrain, ytrain, Xvalid, yvalid, variance, manual_f, constant,
                    evaluation_id, cfg, set(data.reserved_test_ids))
                details.append(row)
                audits.append(audit)
                features.extend(selected)
                predictions.extend(oof)
                training_predictions.extend(tr)
                warning_rows.extend(caught)
                score_arrays[f"{method}__{evaluation_id:03d}"] = scores
            a, b = details[-2:]
            report(f"划分 {evaluation_id:03d}/100（已拟合{len(details)}/200）："
                   f"方差F1={a['validation_macro_f1']:.6f}，ANOVA F1={b['validation_macro_f1']:.6f}；"
                   f"训练折常量={int(constant.sum())}，ANOVA未定义F={audits[-1]['n_undefined_selector_scores']}，所选均有限。")
            if evaluation_id % 5 == 0:
                checkpoint()
        checkpoint()
        np.savez_compressed(output / "training_fold_feature_scores.npz", **score_arrays)
        if hashlib.sha256(cfg.split_manifest_path.read_bytes()).hexdigest() != manifest_sha:
            raise AssertionError("固定划分清单被意外修改")
        from top50_results import summarize_results
        summarize_results(output, data, parent, identity)
        from top50_visualization import plot_all
        plot_all(output)
        status.update(status="complete", new_classifier_fits_completed=len(details),
                      elapsed_seconds=time.perf_counter() - start, all_fit_audits_passed=True)
        write_json(output / "stage_status.json", status)
        write_json(cfg.output_dir / "latest_top50_comparison.json", {"run_directory": str(output.relative_to(cfg.output_dir)), "status": "complete"})
        report(f"200次模型拟合完成；结果：{output}")
        return output
    except Exception as exc:
        checkpoint()
        status.update(status="failed", new_classifier_fits_completed=len(details), error=str(exc), elapsed_seconds=time.perf_counter() - start)
        write_json(output / "stage_status.json", status)
        (output / "error_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        report(f"失败并保留已完成结果：{exc}")
        raise
    finally:
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    config = replace(ExperimentConfig(), cv_mode="repeated")
    if args.archive:
        config = replace(config, raw_archive=args.archive.resolve())
    if args.data_dir:
        config = replace(config, data_dir=args.data_dir.resolve())
    try:
        run(config)
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
