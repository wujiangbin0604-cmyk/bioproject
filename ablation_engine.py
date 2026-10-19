# -*- coding: utf-8 -*-
"""完整消融实验的拟合、审计和原子断点；复用既有 Pipeline 工厂。"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import accuracy_score
from threadpoolctl import threadpool_limits

from baseline import build_baseline
from config import CLASS_ORDER
from cross_validation import frozen_pipeline_record
from evaluation import compute_metrics
from feature_selection import build_anova_pipeline
from variance_topk import VarianceTopK

METHODS = ("variance_svm", "anova_svm", "anova_lr")
SELECTORS = ("variance", "anova", "svc_l2")
METRICS = ("macro_f1", "balanced_accuracy", "accuracy")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    """完成标志最后写入，避免把中断文件误认为有效断点。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def save_checkpoint(path, metadata, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp.npz")
    np.savez_compressed(temp, **arrays)
    os.replace(temp, path.with_suffix(".npz"))
    atomic_json(path.with_suffix(".json"), {**metadata, "arrays_sha256": sha256(path.with_suffix(".npz"))})


def load_checkpoint(path, identity):
    path = Path(path)
    if not path.with_suffix(".json").exists():
        return None
    record = read_json(path.with_suffix(".json"))
    if record["identity"] != identity or sha256(path.with_suffix(".npz")) != record["arrays_sha256"]:
        raise ValueError(f"断点配置或内容校验失败：{path}")
    with np.load(path.with_suffix(".npz"), allow_pickle=False) as bundle:
        arrays = {k: bundle[k] for k in bundle.files}
    return record, arrays


def build_pipeline(cfg, method, k):
    if method == "full_svm":
        return build_baseline(cfg)
    pipeline = build_anova_pipeline(cfg, k, "logistic_regression" if method == "anova_lr" else "linear_svm", C=1.0)
    if method == "variance_svm":
        pipeline.set_params(select=VarianceTopK(k=k))
    elif method == "anova_lr":
        # sklearn 1.8 的 penalty 参数已弃用：l1_ratio=0 明确表示纯 L2，lbfgs 支持多分类。
        pipeline.set_params(model__l1_ratio=0.0)
    elif method != "anova_svm":
        raise ValueError(method)
    return pipeline


def scores(y, predicted):
    return {**compute_metrics(y, predicted), "accuracy": float(accuracy_score(y, predicted))}


def raw_training_statistics(X, y):
    """独立均方比实现，用来核验当前训练折的实际 ANOVA 分数。"""
    variance, constant = X.var(axis=0, ddof=1), np.ptp(X, axis=0) == 0
    mean = X.mean(axis=0)
    between, within = np.zeros(X.shape[1]), np.zeros(X.shape[1])
    for label in CLASS_ORDER:
        group = X[y == label]
        mu = group.mean(axis=0)
        between += len(group) * (mu - mean) ** 2
        within += ((group - mu) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = (between / (len(CLASS_ORDER) - 1)) / (within / (len(X) - len(CLASS_ORDER)))
    f[constant] = np.nan
    if not np.isfinite(variance).all() or np.isinf(f).any() or np.any(np.isnan(f) & ~constant):
        raise ValueError("当前训练子集方差/ANOVA 出现无法解释的非有限值")
    return variance, f, constant


def validate_anova(actual, manual, constant):
    if np.isinf(actual).any() or np.any(np.isnan(actual) & ~constant):
        raise ValueError("ANOVA：非恒定基因 NaN 或无限 F-score，停止并保留诊断")
    if np.any(actual[np.isfinite(actual)] < 0) or not np.isnan(actual[constant]).all():
        raise ValueError("ANOVA：负分数或恒定基因处理不符")
    np.testing.assert_allclose(actual[~constant], manual[~constant], rtol=1e-6, atol=1e-6)


def rank_scores(values, method):
    if method == "anova":
        # 完全跟随 SelectKBest 的稳定升序取最后 K 列规则；NaN 只在排名副本中置 -inf。
        return np.argsort(np.where(np.isnan(values), -np.inf, values), kind="stable")[::-1]
    return np.argsort(-values, kind="stable")  # 并列时原列号小的优先。


def fit_classification_task(X, y, train, valid, method, k, evaluation_id, cfg,
                            checkpoint, identity, statistics):
    """训练矩阵以 ndarray 进入 Pipeline；索引在调用前审计，实际 fit 输入逐步追踪。"""
    if load_checkpoint(checkpoint, identity) is not None:
        return {"method": method, "k": k, "evaluation_id": evaluation_id, "resumed": True}
    Xtrain, Xvalid, ytrain, yvalid = X[train], X[valid], y[train], y[valid]
    variance, manual_f, constant = statistics
    fitted = clone(build_pipeline(cfg, method, k))
    selector, scaler, model = [fitted.named_steps[s] for s in ("select", "scale", "model")]
    assert not hasattr(selector, "n_features_in_") and not hasattr(scaler, "mean_") and not hasattr(model, "coef_")
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg.numeric_threads):
        warnings.simplefilter("always")
        with patch.object(selector, "fit", wraps=selector.fit) as sf, \
             patch.object(scaler, "fit", wraps=scaler.fit) as zf, \
             patch.object(model, "fit", wraps=model.fit) as mf:
            start = time.perf_counter()
            fitted.fit(Xtrain, ytrain)
            fit_seconds = time.perf_counter() - start
            assert (sf.call_count, zf.call_count, mf.call_count) == (1, 1, 1)
            np.testing.assert_array_equal(sf.call_args.args[0], Xtrain)
            np.testing.assert_array_equal(sf.call_args.args[1], ytrain)
            np.testing.assert_array_equal(mf.call_args.args[1], ytrain)
            actual_scaled_input = zf.call_args.args[0]
            actual_model_input = mf.call_args.args[0]
        start = time.perf_counter()
        train_pred, valid_pred = fitted.predict(Xtrain), fitted.predict(Xvalid)
        predict_seconds = time.perf_counter() - start
    warning_rows = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        atomic_json(Path(checkpoint).with_suffix(".failure.json"), {"identity": identity, "warnings": warning_rows})
        raise RuntimeError(f"{method} K={k} fold={evaluation_id} 未收敛；不静默丢弃该折")
    support = selector.get_support()
    assert support.sum() == k and selector.n_features_in_ == X.shape[1]
    selected = np.flatnonzero(support)
    selector_method = "variance" if method == "variance_svm" else "anova"
    if selector_method == "variance":
        actual_scores = selector.variances_
        np.testing.assert_allclose(actual_scores, variance, rtol=1e-12, atol=1e-12)
        assert selector.n_samples_seen_ == len(train)
    else:
        actual_scores = selector.scores_
        validate_anova(actual_scores, manual_f, constant)
    rank = rank_scores(actual_scores, selector_method)
    np.testing.assert_array_equal(np.sort(rank[:k]), selected)
    assert np.isfinite(actual_scores[selected]).all() and not constant[selected].any()
    raw_selected = Xtrain[:, selected]
    np.testing.assert_array_equal(actual_scaled_input, raw_selected)
    np.testing.assert_allclose(actual_model_input, scaler.transform(raw_selected), rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(scaler.mean_, raw_selected.mean(axis=0), rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(scaler.var_, raw_selected.var(axis=0), rtol=1e-10, atol=1e-12)
    assert np.all(np.asarray(scaler.n_samples_seen_) == len(train))
    assert model.n_features_in_ == k and np.isfinite(model.coef_).all()
    metrics = {"method": method, "k": k, "evaluation_id": evaluation_id,
               "repeat_id": (evaluation_id - 1) // 5 + 1, "fold_id": (evaluation_id - 1) % 5 + 1,
               "n_train": len(train), "n_validation": len(valid), "C": 1.0,
               "fit_seconds": fit_seconds, "predict_seconds": predict_seconds,
               "max_solver_iterations": int(np.max(np.atleast_1d(model.n_iter_))),
               "result_origin": "new_fit", "convergence_warning_count": 0}
    ts, vs = scores(ytrain, train_pred), scores(yvalid, valid_pred)
    for name in METRICS:
        metrics.update({f"train_{name}": ts[name], f"validation_{name}": vs[name], f"gap_{name}": ts[name] - vs[name]})
    audit = {"method": method, "k": k, "evaluation_id": evaluation_id,
             "repeat_id": metrics["repeat_id"], "fold_id": metrics["fold_id"],
             "train_validation_overlap": 0, "reserved_test_overlap": 0,
             "pipeline_unfitted_before_fit": True, "selector_fit_calls": 1, "scaler_fit_calls": 1,
             "classifier_fit_calls": 1, "selector_fit_samples": len(train),
             "selector_fit_features": X.shape[1], "scaler_training_samples": len(train),
             "scaler_features": k, "selector_input_matches_training": True,
             "selector_scores_match_training_statistics": True, "scaler_fit_audit_passed": True,
             "classifier_input_is_training_scaled": True, "n_constant_training_genes": int(constant.sum()),
             "n_undefined_selector_scores": int(np.isnan(actual_scores).sum()),
             "selected_scores_all_finite": True, "result_origin": "new_fit"}
    all_ranks = np.empty(X.shape[1], dtype=int)
    all_ranks[rank] = np.arange(1, X.shape[1] + 1)
    save_checkpoint(checkpoint, {"identity": identity, "metrics": metrics, "audit": audit, "warnings": warning_rows},
                    train_pred=train_pred.astype(str), valid_pred=valid_pred.astype(str), selected=selected,
                    selection_rank=all_ranks[selected], selector_score=actual_scores[selected],
                    training_variance=variance[selected], training_anova_f_score=manual_f[selected])
    return {"method": method, "k": k, "evaluation_id": evaluation_id, "resumed": False,
            "validation_macro_f1": vs["macro_f1"], "fit_seconds": fit_seconds}


def import_previous_results(cfg, data, run, fold_records, identity):
    """只复用完全同配置、同样本顺序、同划分且保有实际训练/OOF预测的历史拟合。"""
    from top50_comparison import build_comparison_pipelines
    sources = []
    imported = 0
    for pointer_name, is_full in (("latest_repeated_cv.json", True), ("latest_top50_comparison.json", False)):
        pointer = read_json(cfg.output_dir / pointer_name)
        source = cfg.output_dir / pointer["run_directory"]
        original = read_json(source / "config.json")
        checks = {
            "complete": pointer["status"] == "complete" and read_json(source / "stage_status.json")["status"] == "complete",
            "manifest_identical": read_json(source / "split_manifest.json") == read_json(cfg.split_manifest_path),
            "development_fingerprint_identical": read_json(source / "development_data_record.json")["development_fingerprint_sha256"] == read_json(run / "development_data_record.json")["development_fingerprint_sha256"],
            "all_fold_indices_identical": read_json(source / "cv_fold_indices.json")["folds"] == fold_records,
            "configuration_identical": all(original[key] == cfg.to_dict()[key] for key in ("random_state", "n_splits", "n_repeats", "cv_mode", "baseline_c", "max_iter", "tolerance", "class_weight", "numeric_threads")),
            "not_permuted": not original.get("label_permutation_enabled", False),
        }
        environment = read_json(source / "environment.json")
        checks["numeric_library_versions_identical"] = all(
            environment.get(old_key) == importlib.metadata.version(package)
            for old_key, package in (("numpy", "numpy"), ("pandas", "pandas"),
                                     ("scikit_learn", "scikit-learn"), ("scipy", "scipy")))
        if is_full:
            checks["pipeline_identical"] = frozen_pipeline_record(build_baseline(cfg), "full_linear_svm", "none", "all") == read_json(source / "frozen_pipeline.json")
            file_names = ("repeated_cv_fold_results.csv", "repeated_cv_oof_predictions.csv", "training_predictions.csv", "repeated_cv_fit_audit.csv")
            old_methods = {"full_svm": "full_svm"}
            selected_table = None
        else:
            current = build_comparison_pipelines(cfg)
            frozen = read_json(source / "frozen_pipelines.json")
            checks["pipeline_identical"] = all(frozen_pipeline_record(p, name, "variance" if name.startswith("variance") else "anova", 50) == frozen[name] for name, p in current.items())
            file_names = ("top50_comparison_fold_results.csv", "top50_oof_predictions.csv", "top50_training_predictions.csv", "top50_cv_fit_audit.csv", "top50_selected_features_by_fold.csv")
            old_methods = {"variance_top50_svm": "variance_svm", "anova_top50_svm": "anova_svm"}
            selected_table = pd.read_csv(source / file_names[-1])
        record = {"source": str(source), "checks": checks, "allowed": all(checks.values()),
                  "files_sha256": {name: sha256(source / name) for name in file_names}}
        sources.append(record)
        if not record["allowed"]:
            continue  # 不能证实时，由后续正式循环重新拟合，绝不配对猜测。
        details, oof, training, audits = [pd.read_csv(source / name) for name in file_names[:4]]
        for old_method, method in old_methods.items():
            k = 20531 if is_full else 50
            sub = details if is_full else details.loc[details.method.eq(old_method)]
            assert len(sub) == 100
            for e, row in sub.set_index("evaluation_id").iterrows():
                path = run / "classification" / "checkpoints" / f"{method}_k{k}_{e:03d}"
                if load_checkpoint(path, identity) is not None:
                    continue
                definition = fold_records[e - 1]
                op = oof.loc[oof.evaluation_id.eq(e)]
                tp = training.loc[training.evaluation_id.eq(e)]
                au = audits.loc[audits.evaluation_id.eq(e)]
                if not is_full:
                    op, tp, au = [v.loc[v.method.eq(old_method)] for v in (op, tp, au)]
                assert op.sample_id.tolist() == definition["validation_sample_ids"]
                assert tp.sample_id.tolist() == definition["train_sample_ids"]
                assert np.array_equal(op.y_true, data.y.loc[op.sample_id]) and np.array_equal(tp.y_true, data.y.loc[tp.sample_id])
                assert len(au) == 1
                audit = au.iloc[0].to_dict()
                assert audit["reserved_test_overlap"] == 0 and audit["train_validation_overlap"] == 0 and bool(audit["scaler_fit_audit_passed"])
                for part, preds in (("train", tp), ("validation", op)):
                    calculated = scores(preds.y_true, preds.y_pred)
                    for name in ("macro_f1", "balanced_accuracy"):
                        np.testing.assert_allclose(calculated[name], row[f"{part}_{name}"], rtol=1e-12, atol=1e-12)
                metrics = {"method": method, "k": k, "evaluation_id": int(e), "repeat_id": definition["repeat"], "fold_id": definition["fold"],
                           "n_train": len(tp), "n_validation": len(op), "C": 1.0,
                           "fit_seconds": float(row.fit_seconds), "predict_seconds": float(row.predict_seconds),
                           "max_solver_iterations": int(row.max_solver_iterations), "result_origin": "verified_prior_fit", "convergence_warning_count": 0}
                ts, vs = scores(tp.y_true, tp.y_pred), scores(op.y_true, op.y_pred)
                for name in METRICS:
                    metrics.update({f"train_{name}": ts[name], f"validation_{name}": vs[name], f"gap_{name}": ts[name] - vs[name]})
                arrays = {"train_pred": tp.y_pred.to_numpy(dtype=str), "valid_pred": op.y_pred.to_numpy(dtype=str)}
                if selected_table is not None:
                    selected = selected_table.loc[selected_table.method.eq(old_method) & selected_table.evaluation_id.eq(e)].sort_values("original_column_index")
                    assert len(selected) == k and selected.gene_id.nunique() == k
                    np.testing.assert_array_equal(data.X.columns[selected.original_column_index], selected.gene_id)
                    arrays.update(selected=selected.original_column_index.to_numpy(), selection_rank=selected.selection_rank.to_numpy(),
                                  selector_score=selected.selector_score.to_numpy(), training_variance=selected.training_variance.to_numpy(),
                                  training_anova_f_score=selected.training_anova_f_score.to_numpy())
                audit.update(method=method, k=k, evaluation_id=int(e), repeat_id=definition["repeat"], fold_id=definition["fold"], result_origin="verified_prior_fit", source_audit_file=str(source / file_names[3]))
                save_checkpoint(path, {"identity": identity, "metrics": metrics, "audit": audit, "warnings": [], "prior_source": str(source)}, **arrays)
                imported += 1
    atomic_json(run / "logs" / "reuse_audit.json", {"sources": sources, "imported_this_invocation": imported,
                "note": "历史拟合时间保留为原运行测量值；Accuracy 从实际保存的预测重新计算；不把导入称为新拟合。"})
    return sources


def fit_full_baseline_task(X, y, train, valid, e, cfg, path, identity):
    """无法证实旧基线一致时，在同一开发折明确重跑，仍不接触测试集。"""
    if load_checkpoint(path, identity) is not None:
        return
    model = build_baseline(cfg)
    raw, labels = X[train], y[train]
    scaler, classifier = model.named_steps["scale"], model.named_steps["model"]
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg.numeric_threads):
        warnings.simplefilter("always")
        with patch.object(scaler, "fit", wraps=scaler.fit) as sf, patch.object(classifier, "fit", wraps=classifier.fit) as mf:
            start = time.perf_counter()
            model.fit(raw, labels)
            seconds = time.perf_counter() - start
            assert sf.call_count == mf.call_count == 1
            np.testing.assert_array_equal(sf.call_args.args[0], raw)
            np.testing.assert_array_equal(mf.call_args.args[1], labels)
            np.testing.assert_allclose(mf.call_args.args[0], scaler.transform(raw), rtol=1e-12, atol=1e-12)
        start = time.perf_counter()
        tp, vp = model.predict(raw), model.predict(X[valid])
        prediction_seconds = time.perf_counter() - start
    warning_rows = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        atomic_json(Path(path).with_suffix(".failure.json"), {"warnings": warning_rows})
        raise RuntimeError(f"全特征基线第{e}折未收敛")
    np.testing.assert_allclose(scaler.mean_, raw.mean(axis=0), rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(scaler.var_, raw.var(axis=0), rtol=1e-10, atol=1e-12)
    assert np.all(np.asarray(scaler.n_samples_seen_) == 512) and classifier.n_features_in_ == 20531
    row = {"method": "full_svm", "k": 20531, "evaluation_id": e, "repeat_id": (e - 1) // 5 + 1,
           "fold_id": (e - 1) % 5 + 1, "n_train": 512, "n_validation": 128, "C": 1.0,
           "fit_seconds": seconds, "predict_seconds": prediction_seconds,
           "max_solver_iterations": int(np.max(np.atleast_1d(classifier.n_iter_))),
           "result_origin": "new_fit", "convergence_warning_count": 0}
    ts, vs = scores(labels, tp), scores(y[valid], vp)
    for name in METRICS:
        row.update({f"train_{name}": ts[name], f"validation_{name}": vs[name], f"gap_{name}": ts[name] - vs[name]})
    audit = {"method": "full_svm", "k": 20531, "evaluation_id": e, "repeat_id": row["repeat_id"], "fold_id": row["fold_id"],
             "train_validation_overlap": 0, "reserved_test_overlap": 0, "scaler_training_samples": 512,
             "scaler_features": 20531, "scaler_fit_audit_passed": True, "scaler_fit_calls": 1, "classifier_fit_calls": 1,
             "pipeline_unfitted_before_fit": True, "result_origin": "new_fit"}
    save_checkpoint(path, {"identity": identity, "metrics": row, "audit": audit, "warnings": warning_rows},
                    train_pred=tp.astype(str), valid_pred=vp.astype(str))
