# -*- coding: utf-8 -*-
"""标准/重复分层 CV；所有拟合都在开发集的当前训练折内进行。"""
from __future__ import annotations

import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from config import ExperimentConfig
from data_loader import DevelopmentData, write_json
from evaluation import compute_metrics, summarize_cv


def frozen_pipeline_record(estimator: Pipeline, model_id: str,
                           selection_method: str, k: int | str) -> dict:
    """记录完整未拟合流水线配置，供第六阶段核对；不根据重复CV分数再选模型。"""
    def encode(value):
        if hasattr(value, "get_params"):
            return {"class": type(value).__module__ + "." + type(value).__name__,
                    "parameters": {name: encode(v) for name, v in value.get_params(deep=False).items()}}
        if isinstance(value, (tuple, list)):
            return [encode(item) for item in value]
        if callable(value):
            return value.__module__ + "." + value.__qualname__
        if isinstance(value, np.generic):
            return value.item()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise TypeError(f"配置不能序列化：{type(value)}")
    return {"model_id": model_id, "selection_method": selection_method, "k": k,
            "pipeline_steps": [[name, encode(step)] for name, step in estimator.steps]}


def make_cv(cfg: ExperimentConfig):
    """repeated 模式是 20 次重新随机分层的 5 折划分，合计 100 次验证。"""
    if cfg.cv_mode == "standard":
        return StratifiedKFold(n_splits=cfg.n_splits, shuffle=True, random_state=cfg.random_state)
    if cfg.cv_mode == "repeated":
        return RepeatedStratifiedKFold(n_splits=cfg.n_splits, n_repeats=cfg.n_repeats,
                                      random_state=cfg.random_state)
    raise ValueError("CV_MODE 必须为 standard 或 repeated")


def _audit_fold_pipeline(fitted: Pipeline, X_train: pd.DataFrame) -> dict:
    """核对 scaler 的样本数、均值及方差确实来自训练折。"""
    expected = X_train.to_numpy(dtype=float)
    if "select" in fitted.named_steps:
        expected = expected[:, fitted.named_steps["select"].get_support()]
    scaler = fitted.named_steps["scale"]
    means, variances = expected.mean(axis=0), expected.var(axis=0, ddof=0)
    np.testing.assert_allclose(scaler.mean_, means, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(scaler.var_, variances, rtol=1e-10, atol=1e-12)
    if not np.all(np.asarray(scaler.n_samples_seen_) == len(X_train)):
        raise AssertionError("标准化器使用的样本数不是当前训练折大小")
    return {
        "scaler_training_samples": len(X_train), "scaler_features": len(means),
        "scaler_mean_max_abs_error": float(np.max(np.abs(scaler.mean_ - means))),
        "scaler_variance_max_abs_error": float(np.max(np.abs(scaler.var_ - variances))),
        "scaler_fit_audit_passed": True,
    }


def evaluate_fixed_pipeline(estimator: Pipeline, development: DevelopmentData,
                            cfg: ExperimentConfig, output: Path,
                            model_id: str = "full_linear_svm", selection_method: str = "none",
                            k: int | str = "all", frozen_configuration: dict | None = None,
                            checkpoint_every: int = 0,
                            record_training_predictions: bool = False) -> dict:
    """评估一个固定 Pipeline 配置，记录每折训练/验证分数、索引和拟合审计。

    此函数本身不进行超参数搜索。重复模式必须提供已冻结配置，仅描述波动，
    不能随后重新挑选参数并把同一组分数报告为无偏性能。
    """
    if not isinstance(development, DevelopmentData):
        raise TypeError("只接受 DevelopmentData，不能传入整套数据或测试集")
    if not isinstance(estimator, Pipeline) or not {"scale", "model"}.issubset(estimator.named_steps):
        raise TypeError("模型必须为包含 scale、model 的未拟合 sklearn Pipeline")
    if cfg.cv_mode == "repeated" and frozen_configuration is None:
        raise ValueError("重复CV只评估已冻结配置，必须提供 frozen_configuration")
    if cfg.cv_mode == "repeated":
        actual = frozen_pipeline_record(estimator, model_id, selection_method, k)
        if frozen_configuration != actual:
            raise ValueError("实际 Pipeline 配置与冻结配置不一致")
    X, y = development.X, development.y
    if not X.index.equals(y.index):
        raise ValueError("开发集 X 与 y 未按 ID 对齐")
    if set(X.index) & set(development.reserved_test_ids):
        raise ValueError("开发集混入了保留测试样本")
    cv = make_cv(cfg)
    output.mkdir(parents=True, exist_ok=True)
    details, predictions, audit, folds, warning_rows = [], [], [], [], []
    training_predictions = []
    validation_counts = np.zeros(len(X), dtype=int)

    def save_checkpoint() -> None:
        """按轮保存已完成结果；中断时不会把部分结果标记为完整实验。"""
        pd.DataFrame(details).to_csv(output / "cv_fold_details.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(predictions).to_csv(output / "development_oof_predictions.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(audit).to_csv(output / "fold_fit_audit.csv", index=False, encoding="utf-8-sig")
        write_json(output / "cv_fold_indices.json", {"cv_mode": cfg.cv_mode, "folds": folds})
        write_json(output / "warnings.json", {"warnings": warning_rows})
        if record_training_predictions:
            pd.DataFrame(training_predictions).to_csv(
                output / "training_predictions.csv", index=False, encoding="utf-8-sig")

    for evaluation_id, (train, valid) in enumerate(cv.split(X, y), start=1):
        repeat = (evaluation_id - 1) // cfg.n_splits + 1
        fold = (evaluation_id - 1) % cfg.n_splits + 1
        X_train, y_train = X.iloc[train], y.iloc[train]
        X_valid, y_valid = X.iloc[valid], y.iloc[valid]
        overlap = set(X_train.index) & set(X_valid.index)
        test_overlap = (set(X_train.index) | set(X_valid.index)) & set(development.reserved_test_ids)
        if overlap or test_overlap:
            raise AssertionError("训练折/验证折/保留测试集存在交集")
        fitted = clone(estimator)
        fresh = not hasattr(fitted.named_steps["scale"], "mean_") and not hasattr(fitted.named_steps["model"], "coef_")
        if not fresh:
            raise AssertionError("本折 Pipeline 未从未拟合状态开始")
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg.numeric_threads):
            warnings.simplefilter("always")
            start = time.perf_counter()
            fitted.fit(X_train, y_train)
            fit_seconds = time.perf_counter() - start
            start = time.perf_counter()
            train_pred, valid_pred = fitted.predict(X_train), fitted.predict(X_valid)
            predict_seconds = time.perf_counter() - start
        for warning in caught:
            warning_rows.append({"evaluation_id": evaluation_id,
                                 "category": warning.category.__name__, "message": str(warning.message)})
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            write_json(output / "warnings.json", {"warnings": warning_rows})
            raise RuntimeError(f"第 {evaluation_id} 折未收敛；请提高 max_iter 后重新运行，不调整 C 来掩盖数值问题")
        fit_audit = _audit_fold_pipeline(fitted, X_train)
        model = fitted.named_steps["model"]
        if model.n_features_in_ != fit_audit["scaler_features"] or not np.isfinite(model.coef_).all():
            raise AssertionError("分类器实际输入特征或拟合系数异常")
        train_scores, valid_scores = compute_metrics(y_train, train_pred), compute_metrics(y_valid, valid_pred)
        row = {
            "model_id": model_id, "selection_method": selection_method, "k": k,
            "C": float(fitted.named_steps["model"].C), "cv_mode": cfg.cv_mode,
            "evaluation_id": evaluation_id, "repeat": repeat, "fold": fold,
            "n_train": len(train), "n_validation": len(valid),
            "n_features_input": X.shape[1], "n_features_model": fit_audit["scaler_features"],
            "fit_seconds": fit_seconds, "predict_seconds": predict_seconds,
            "max_solver_iterations": int(np.max(np.atleast_1d(fitted.named_steps["model"].n_iter_))),
        }
        for metric in train_scores:
            row[f"train_{metric}"] = train_scores[metric]
            row[f"validation_{metric}"] = valid_scores[metric]
            row[f"gap_{metric}"] = train_scores[metric] - valid_scores[metric]
        details.append(row)
        audit.append({"evaluation_id": evaluation_id, "train_validation_overlap": len(overlap),
                      "repeat": repeat, "fold": fold,
                      "reserved_test_overlap": len(test_overlap),
                      "pipeline_unfitted_before_fold": fresh,
                      "model_features_in": int(model.n_features_in_),
                      "model_C": float(model.C), "model_random_state": int(model.random_state),
                      **fit_audit})
        folds.append({"evaluation_id": evaluation_id, "repeat": repeat, "fold": fold,
                      "train_sample_ids": X_train.index.tolist(),
                      "validation_sample_ids": X_valid.index.tolist()})
        predictions.extend({"evaluation_id": evaluation_id, "repeat": repeat, "fold": fold,
                            "sample_id": sid, "y_true": truth, "y_pred": pred}
                           for sid, truth, pred in zip(X_valid.index, y_valid, valid_pred))
        if record_training_predictions:
            training_predictions.extend({"evaluation_id": evaluation_id, "repeat": repeat, "fold": fold,
                                         "sample_id": sid, "y_true": truth, "y_pred": pred}
                                        for sid, truth, pred in zip(X_train.index, y_train, train_pred))
        validation_counts[valid] += 1
        if checkpoint_every:
            write_json(output / "cv_progress.json", {
                "completed_evaluations": evaluation_id, "total_evaluations": cv.get_n_splits(),
                "completed_rounds": evaluation_id // cfg.n_splits,
                "elapsed_fit_seconds": float(sum(item["fit_seconds"] for item in details)),
            })
            if evaluation_id % checkpoint_every == 0:
                save_checkpoint()
        print(f"  {evaluation_id}/{cv.get_n_splits()}：训练 {len(train)}，验证 {len(valid)}，"
              f"Macro-F1={valid_scores['macro_f1']:.6f}，"
              f"Balanced Accuracy={valid_scores['balanced_accuracy']:.6f}", flush=True)
    expected_count = 1 if cfg.cv_mode == "standard" else cfg.n_repeats
    if not np.all(validation_counts == expected_count):
        raise AssertionError("部分开发样本的折外验证次数异常")
    details_df = pd.DataFrame(details)
    predictions_df = pd.DataFrame(predictions)
    summary = summarize_cv(details_df)
    details_df.to_csv(output / "cv_fold_details.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output / "cv_summary.csv", index=False, encoding="utf-8-sig")
    predictions_df.to_csv(output / "development_oof_predictions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(audit).to_csv(output / "fold_fit_audit.csv", index=False, encoding="utf-8-sig")
    write_json(output / "cv_fold_indices.json", {"cv_mode": cfg.cv_mode, "folds": folds})
    write_json(output / "warnings.json", {"warnings": warning_rows})
    if record_training_predictions:
        pd.DataFrame(training_predictions).to_csv(
            output / "training_predictions.csv", index=False, encoding="utf-8-sig")
    return {"details": details_df, "summary": summary, "predictions": predictions_df,
            "audit": pd.DataFrame(audit), "folds": folds}


if __name__ == "__main__":
    from dataclasses import replace
    cfg = ExperimentConfig()
    print(f"standard：{make_cv(cfg).get_n_splits()} 次验证")
    print(f"repeated：{make_cv(replace(cfg, cv_mode='repeated')).get_n_splits()} 次验证（不是100折；未执行拟合）")
