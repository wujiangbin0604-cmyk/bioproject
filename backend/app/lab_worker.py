# -*- coding: utf-8 -*-
"""每个现场CV任务独占一个子进程。仅严格读取既有640例开发行。"""
from __future__ import annotations

import hashlib
import csv as csv_module
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import warnings
import threading
from datetime import datetime, timezone

# 必须在导入numpy/sklearn之前设置；运行入口也设置同样的环境。
for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, classification_report
from sklearn.model_selection import StratifiedKFold, RepeatedStratifiedKFold
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from backend.app.lab_config import ExperimentRequest, DEVELOPMENT_SHA, TERMINAL, atomic_json, read_json
from baseline import build_baseline
from config import ExperimentConfig
from backend.app.services.development_data import load_lab_development
from deployment.lab_registry import SPLIT_SHA, sha256
from feature_selection import build_anova_pipeline
from variance_topk import VarianceTopK


def build_pipeline(request: ExperimentRequest):
    """复用研究项目原有工厂，每一折重新克隆完整Pipeline。"""
    cfg = ExperimentConfig(baseline_c=request.c)
    if request.selection == "anova":
        return build_anova_pipeline(cfg, request.k, request.classifier, request.c)
    # 复用原LR参数，随后按合法选择方案替换选择器。
    if request.classifier == "logistic_regression":
        base = Pipeline(build_anova_pipeline(cfg, request.k, request.classifier, request.c).steps[1:])
    else:
        base = build_baseline(cfg)
    return Pipeline([("select", VarianceTopK(request.k)), *base.steps]) if request.selection == "variance" else base


def metrics(y, predicted):
    return {"macro_f1": float(f1_score(y, predicted, average="macro", zero_division=0)),
            "balanced_accuracy": float(balanced_accuracy_score(y, predicted)),
            "accuracy": float(accuracy_score(y, predicted))}


def csv(path, rows):
    temporary = path.with_suffix(".csv.tmp")
    pd.DataFrame(rows).to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def run(directory: Path):
    state = read_json(directory / "state.json")
    request = ExperimentRequest.model_validate(state["configuration"])
    started = time.perf_counter()
    state_lock = threading.RLock()

    def publish(**fields):
        with state_lock:
            state.update(fields)
            state["revision"] += 1
            state["elapsed_seconds"] = (datetime.now(timezone.utc) - datetime.fromisoformat(state["created_at"])).total_seconds()
            atomic_json(directory / "state.json", state)

    def watch_owner():
        import psutil
        while True:
            time.sleep(1)
            with state_lock:
                if state["status"] in TERMINAL:
                    return
            try:
                alive = psutil.Process(state["owner_pid"]).create_time() == state["owner_started"]
            except psutil.Error:
                alive = False
            if not alive:
                publish(status="interrupted", message="API所有者已退出，工作进程停止以避免失去资源监控")
                os._exit(2)

    threading.Thread(target=watch_owner, daemon=True).start()

    try:
        publish(status="loading", message="正在核对固定划分并且只解析640例开发行", worker_pid=os.getpid())
        cfg = ExperimentConfig()
        if sha256(cfg.split_manifest_path) != SPLIT_SHA:
            raise ValueError("固定640/161划分清单摘要不符，拒绝临时重划分")
        if sys.platform == "linux":
            # 内存紧张时优先终止训练子进程；不把这项偏好称为单进程硬RSS配额。
            try:
                Path("/proc/self/oom_score_adj").write_text("500", encoding="ascii")
            except OSError:
                pass
        dev = load_lab_development(cfg, directory)
        record = read_json(directory / "development_data_record.json")
        if record["development_fingerprint_sha256"] != DEVELOPMENT_SHA:
            raise ValueError("开发数据指纹与历史冻结记录不一致")
        atomic_json(directory / "environment.json", {"python": platform.python_version(), "numpy": np.__version__,
                    "pandas": pd.__version__, "scikit-learn": sklearn.__version__, "random_state": 42,
                    "numeric_threads": 1, "pipeline_parameters": str(build_pipeline(request)),
                    "worker_source_sha256": sha256(Path(__file__)), "development_fingerprint_sha256": DEVELOPMENT_SHA})
        splitter = (RepeatedStratifiedKFold(n_splits=5, n_repeats=20, random_state=42)
                    if request.cv_mode == "repeated" else StratifiedKFold(n_splits=5, shuffle=True, random_state=42))
        indices = list(splitter.split(dev.X, dev.y))
        folds, predictions, audits, rounds, per_class = [], [], [], [], []
        fold_indices = []
        publish(status="running", message="开发集校验完成；各折独立拟合Pipeline", data_audit={
            "development_samples": 640, "raw_features": 20531, "reserved_values_parsed": False,
            "reserved_labels_parsed": False, "split_sha256": SPLIT_SHA, "development_sha256": DEVELOPMENT_SHA})
        template = build_pipeline(request)
        for index, (train, valid) in enumerate(indices):
            repeat_id, fold_id = index // 5 + 1, index % 5 + 1
            Xtrain, Xvalid, ytrain, yvalid = dev.X.iloc[train], dev.X.iloc[valid], dev.y.iloc[train], dev.y.iloc[valid]
            train_ids, valid_ids = list(Xtrain.index), list(Xvalid.index)
            reserved = set(dev.reserved_test_ids)
            if set(train_ids) & set(valid_ids) or (set(train_ids) | set(valid_ids)) & reserved:
                raise ValueError("训练、验证或保留ID交叉，停止")
            pipeline = clone(template)
            begin = time.perf_counter()
            with warnings.catch_warnings(record=True) as recorded, threadpool_limits(limits=1):
                warnings.simplefilter("always")
                pipeline.fit(Xtrain, ytrain)
            fit_seconds = time.perf_counter() - begin
            if any(issubclass(w.category, ConvergenceWarning) for w in recorded):
                raise ValueError("分类器未收敛；该折不作为有效结果。查看worker.log")
            selector = pipeline.named_steps.get("select")
            mask = np.ones(20531, dtype=bool) if selector is None else selector.get_support()
            if selector is not None and hasattr(selector, "scores_"):
                scores = selector.scores_
                constant = np.ptp(Xtrain.to_numpy(), axis=0) == 0
                if not np.isfinite(scores[mask]).all() or np.isinf(scores).any() or (np.isnan(scores) & ~constant).any():
                    raise ValueError("ANOVA出现不能由训练折常数列解释的异常评分")
            train_values = Xtrain.to_numpy()[:, mask]
            scaler = pipeline.named_steps["scale"]
            mean_ok = np.allclose(scaler.mean_, train_values.mean(axis=0), rtol=1e-10, atol=1e-10)
            var_ok = np.allclose(scaler.var_, train_values.var(axis=0), rtol=1e-10, atol=1e-10)
            if scaler.n_samples_seen_ != 512 or not (mean_ok and var_ok):
                raise ValueError("标准化器拟合范围审计失败")
            begin = time.perf_counter()
            pred_train, pred_valid = pipeline.predict(Xtrain), pipeline.predict(Xvalid)
            predict_seconds = time.perf_counter() - begin
            training, validation = metrics(ytrain, pred_train), metrics(yvalid, pred_valid)
            fold = {"evaluation_index": index + 1, "repeat_id": repeat_id, "fold_id": fold_id,
                    **{"train_" + k: v for k, v in training.items()},
                    **{"validation_" + k: v for k, v in validation.items()},
                    "macro_f1_gap": training["macro_f1"] - validation["macro_f1"],
                    "balanced_accuracy_gap": training["balanced_accuracy"] - validation["balanced_accuracy"],
                    "fit_seconds": fit_seconds, "predict_seconds": predict_seconds, "n_features": int(mask.sum()),
                    "warnings": " | ".join(str(w.message) for w in recorded)}
            folds.append(fold)
            predictions.extend({"repeat_id": repeat_id, "fold_id": fold_id, "sample_id": sid,
                                "true_label": str(true), "predicted_class": str(pred)}
                               for sid, true, pred in zip(valid_ids, yvalid, pred_valid))
            audits.append({"repeat_id": repeat_id, "fold_id": fold_id, "train_count": 512, "validation_count": 128,
                           "train_validation_overlap": 0, "reserved_fit_or_predict_count": 0,
                           "scaler_fit_samples": int(scaler.n_samples_seen_), "scaler_mean_matches_train": bool(mean_ok),
                           "scaler_variance_matches_train": bool(var_ok), "selector_fitted_in_pipeline_on_train_only": True,
                           "train_ids_sha256": hashlib.sha256(json.dumps(train_ids).encode()).hexdigest(),
                           "validation_ids_sha256": hashlib.sha256(json.dumps(valid_ids).encode()).hexdigest()})
            # 全特征重复CV会产生约205万条基因记录，流式落盘避免在内存累积字典。
            feature_path = directory / "selected_features.csv"
            new_file = not feature_path.exists()
            with feature_path.open("a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as handle:
                writer = csv_module.DictWriter(handle, fieldnames=["repeat_id", "fold_id", "gene_id"])
                if new_file:
                    writer.writeheader()
                writer.writerows({"repeat_id": repeat_id, "fold_id": fold_id, "gene_id": str(name)} for name in dev.X.columns[mask])
            fold_indices.append({"repeat_id": repeat_id, "fold_id": fold_id, "train_ids": train_ids, "validation_ids": valid_ids})
            if fold_id == 5:
                oof = [p for p in predictions if p["repeat_id"] == repeat_id]
                if len(oof) != 640 or len({p["sample_id"] for p in oof}) != 640:
                    raise ValueError("轮OOF覆盖不完整或重复")
                truth, predicted = [p["true_label"] for p in oof], [p["predicted_class"] for p in oof]
                rounds.append({"repeat_id": repeat_id, **metrics(truth, predicted)})
                report = classification_report(truth, predicted, output_dict=True, zero_division=0)
                per_class.extend({"repeat_id": repeat_id, "cancer_type": label, **report[label]} for label in sorted(set(truth)))
            for filename, rows in (("fold_results.csv", folds), ("oof_predictions.csv", predictions),
                                   ("fit_audit.csv", audits)):
                csv(directory / filename, rows)
            if rounds:
                csv(directory / "round_results.csv", rounds)
                csv(directory / "per_class_metrics.csv", per_class)
            atomic_json(directory / "cv_indices.json", fold_indices)
            publish(completed_folds=len(folds), folds=folds, rounds=rounds,
                    message=f"已完成第{repeat_id}轮第{fold_id}折（交叉验证验证折）")
        summary = {}
        for prefix, rows, columns in (("fold", folds, ("validation_macro_f1", "validation_balanced_accuracy", "validation_accuracy")),
                                      ("round_oof", rounds, ("macro_f1", "balanced_accuracy", "accuracy"))):
            summary[prefix] = {}
            for column in columns:
                a = np.asarray([row[column] for row in rows])
                summary[prefix][column] = {"n": len(a), "mean": float(a.mean()), "sample_std": float(a.std(ddof=1)) if len(a)>1 else None,
                    "min": float(a.min()), "max": float(a.max()), "median": float(np.median(a))}
        summary["scope"] = "exploratory_fixed_640_development_cv"
        summary["interpretation"] = "相关CV折/轮仅作描述；不是新的保留集或外部验证，也不替换正式研究指标。"
        atomic_json(directory / "summary.json", summary)
        publish(status="completed", summary=summary, message="现场开发集交叉验证完成，未评价保留集")
    except Exception as exc:
        (directory / "worker_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        publish(status="failed", error=f"{type(exc).__name__}: {exc}", message="任务失败；已完成折仍可导出")


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
