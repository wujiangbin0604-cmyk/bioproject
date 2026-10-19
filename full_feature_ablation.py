# -*- coding: utf-8 -*-
"""完整开发集 RQ1/RQ2/RQ3；不启用保留测试集，不进行 C 搜索。"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from threadpoolctl import threadpool_limits

from ablation_engine import (METHODS, atomic_json, build_pipeline, fit_classification_task, fit_full_baseline_task,
                             import_previous_results, load_checkpoint, raw_training_statistics,
                             read_json, sha256)
from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from cross_validation import frozen_pipeline_record, make_cv
from data_loader import load_existing_development_data


def hardware():
    """只读 Windows 物理内存；不依赖可能受限的 WMI 服务。"""
    import ctypes
    from ctypes import wintypes
    class Status(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [(s, ctypes.c_ulonglong) for s in
                    ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
    m = Status()
    m.length = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise OSError("不能读取可用内存")
    return {"logical_cpus": os.cpu_count(), "physical_ram_gib": m.total / 2 ** 30,
            "available_ram_gib": m.available / 2 ** 30, "workspace_free_gib": shutil.disk_usage(PROJECT_DIR).free / 2 ** 30}


def log(run, message):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    with (run / "logs" / "progress.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def fit_with_cache(X, y, train, valid, method, k, e, cfg, path, identity, statistics_path):
    with np.load(statistics_path, allow_pickle=False) as bundle:
        stats = tuple(bundle[name] for name in ("variance", "anova", "constant"))
    return fit_classification_task(X, y, train, valid, method, k, e, cfg, path, identity, stats)


def run_experiment(args):
    cfg = replace(ExperimentConfig(), cv_mode="repeated", n_jobs=args.n_jobs)
    if cfg.n_jobs < 1:
        raise ValueError("n_jobs 必须为正整数，避免 -1 自动耗尽内存")
    hw = hardware()
    # 每个工作进程预留约 0.8 GiB，另保留 0.7 GiB；默认始终为 1。
    safe_jobs = max(1, min(os.cpu_count() or 1, int((hw["available_ram_gib"] - .7) / .8)))
    if cfg.n_jobs > safe_jobs:
        raise MemoryError(f"当前可用内存只允许 n_jobs<={safe_jobs}；请求 {cfg.n_jobs}")
    run = Path(args.resume).resolve() if args.resume else cfg.output_dir / "full_feature_ablation" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for folder in ("classification/checkpoints", "classification/training_scores", "stability/checkpoints", "analysis", "figures", "logs", "logs/source_snapshot"):
        (run / folder).mkdir(parents=True, exist_ok=True)
    log(run, f"开始/恢复完整开发集实验：n_jobs={cfg.n_jobs}；硬件={hw}")
    atomic_json(cfg.output_dir / "latest_full_feature_ablation.json", {"run_directory": str(run.relative_to(cfg.output_dir)), "status": "running"})
    start = time.perf_counter()
    try:
        data = load_existing_development_data(cfg, run, strict_rows_only=True)
        X, y = data.X.to_numpy(dtype=float), data.y.to_numpy(dtype=str)
        ids = data.X.index.to_numpy(dtype=str)
        assert data.X.index.equals(data.y.index) and X.shape == (640, 20531)
        assert not set(ids) & set(data.reserved_test_ids)
        quality = {"n_development": len(X), "n_features": X.shape[1], "n_reserved_excluded": 161,
                   "duplicate_sample_ids": int(data.X.index.duplicated().sum()),
                   "duplicate_expression_rows": int(data.X.duplicated().sum()),
                   "missing_values": int(data.X.isna().sum().sum()), "infinite_values": int(np.isinf(X).sum()),
                   "non_numeric_features": int(sum(not pd.api.types.is_numeric_dtype(t) for t in data.X.dtypes)),
                   "constant_development_genes": int((np.ptp(X, axis=0) == 0).sum()),
                   "class_counts": {c: int((y == c).sum()) for c in CLASS_ORDER},
                   "gene_identifiers_original": True, "labels_aligned_by_sample_id": True}
        atomic_json(run / "logs" / "development_quality.json", quality)
        if any(quality[k] for k in ("duplicate_sample_ids", "duplicate_expression_rows", "missing_values", "infinite_values", "non_numeric_features")):
            raise ValueError("开发集质量检查失败；详见 development_quality.json")
        folds = list(make_cv(cfg).split(X, y))
        definitions = []
        for e, (train, valid) in enumerate(folds, 1):
            assert len(train) == 512 and len(valid) == 128 and not set(train) & set(valid)
            assert not (set(ids[train]) | set(ids[valid])) & set(data.reserved_test_ids)
            definitions.append({"evaluation_id": e, "repeat": (e - 1) // 5 + 1, "fold": (e - 1) % 5 + 1,
                                "train_sample_ids": ids[train].tolist(), "validation_sample_ids": ids[valid].tolist()})
        atomic_json(run / "cv_fold_indices.json", {"cv_mode": "repeated", "folds": definitions})
        pipelines = {f"{method}_k{k}": frozen_pipeline_record(build_pipeline(cfg, method, k), method, "variance" if method.startswith("variance") else "anova", k)
                     for k in cfg.k_values for method in METHODS}
        frozen = {"protocol_version": "rq123-development-v1", "config": {k: v for k, v in cfg.to_dict().items() if k not in ("n_jobs", "output_dir", "data_dir", "split_manifest_path", "raw_archive")},
                  "candidate_delta": .005, "candidate_rule": "abs(baseline_mean - candidate_mean) <= delta; smallest among prelisted K, separately per pipeline",
                  "development_fingerprint": read_json(run / "development_data_record.json")["development_fingerprint_sha256"],
                  "folds_sha256": sha256(run / "cv_fold_indices.json"), "pipelines": pipelines,
                  "coefficient_importance": "sqrt(sum(coef[class,gene] ** 2 over classes)); scaled full-feature SVM on each 512-sample subsample",
                  "subsample_method": "StratifiedShuffleSplit(n_splits=30, train_size=0.8, random_state=42)",
                  "no_hyperparameter_search": True, "no_reserved_test_access": True}
        identity = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        manifest = run / "logs" / "frozen_experiment.json"
        if manifest.exists() and read_json(manifest)["identity"] != identity:
            raise ValueError("恢复请求与原断点的配置/数据/划分不同")
        atomic_json(manifest, {"identity": identity, **frozen})
        env = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(), "hardware": hw,
               "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scikit-learn", "scipy", "matplotlib", "joblib", "threadpoolctl")}}
        atomic_json(run / "logs" / "environment.json", env)
        atomic_json(run / "logs" / "execution_config.json", {**cfg.to_dict(), "effective_n_jobs": cfg.n_jobs, "phase": args.phase})
        for script in ("full_feature_ablation.py", "ablation_engine.py", "ablation_stability.py", "ablation_results.py", "ablation_visualization.py", "verify_full_feature_ablation.py", "data_loader.py", "config.py", "cross_validation.py", "feature_selection.py", "variance_topk.py", "baseline.py", "evaluation.py"):
            source = PROJECT_DIR / script
            if source.exists():
                target = run / "logs" / "source_snapshot" / script
                if not target.exists():
                    shutil.copy2(source, target)
        invocation = run / "logs" / "invocations" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        invocation.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for name in ("full_feature_ablation.py", "ablation_engine.py", "ablation_stability.py", "ablation_results.py", "ablation_report.py", "ablation_visualization.py", "verify_full_feature_ablation.py"):
            if (PROJECT_DIR / name).exists():
                shutil.copy2(PROJECT_DIR / name, invocation / name)
                hashes[name] = sha256(PROJECT_DIR / name)
        atomic_json(invocation / "invocation.json", {"phase": args.phase, "source_sha256": hashes,
                    "initial_classification_snapshot": "logs/source_snapshot", "identity": identity})
        pd.DataFrame({"original_column_index": np.arange(X.shape[1]), "gene_id": data.X.columns}).to_csv(run / "classification" / "gene_catalog.csv", index=False, encoding="utf-8-sig")
        if args.phase in ("all", "classification"):
            sources = import_previous_results(cfg, data, run, definitions, identity)
            log(run, "历史结果复用审计：" + "; ".join(f"{Path(s['source']).name}={s['allowed']}" for s in sources))
            for e, (train, valid) in enumerate(folds, 1):
                p = run / "classification" / "checkpoints" / f"full_svm_k20531_{e:03d}"
                if load_checkpoint(p, identity) is None:
                    log(run, f"旧基线不能安全复用，重跑全特征基线第{e}/100折")
                    fit_full_baseline_task(X, y, train, valid, e, cfg, p, identity)
            for e, (train, valid) in enumerate(folds, 1):
                p = run / "classification" / "training_scores" / f"fold_{e:03d}.npz"
                if p.exists():
                    continue
                with threadpool_limits(limits=1):
                    variance, f, constant = raw_training_statistics(X[train], y[train])
                temp = p.with_suffix(".tmp.npz")
                np.savez_compressed(temp, variance=variance, anova=f, constant=constant)
                os.replace(temp, p)
            # 最小检查即正式实验第一个划分的三次拟合，成功后保留为正式断点。
            for method in METHODS:
                k, e = cfg.k_values[0], 1
                fit_with_cache(X, y, *folds[0], method, k, e, cfg,
                               run / "classification" / "checkpoints" / f"{method}_k{k}_{e:03d}", identity,
                               run / "classification" / "training_scores" / f"fold_{e:03d}.npz")
            log(run, "最小程序检查通过：K=20 的三种 Pipeline、实际输入和训练范围审计均通过，自动继续。")
            from ablation_results import aggregate_classification
            for k in cfg.k_values:
                for method in METHODS:
                    pending = [(e, tr, va) for e, (tr, va) in enumerate(folds, 1)
                               if load_checkpoint(run / "classification" / "checkpoints" / f"{method}_k{k}_{e:03d}", identity) is None]
                    log(run, f"RQ1 {method} K={k}：待拟合 {len(pending)}/100")
                    calls = (delayed(fit_with_cache)(X, y, tr, va, method, k, e, cfg,
                             run / "classification" / "checkpoints" / f"{method}_k{k}_{e:03d}", identity,
                             run / "classification" / "training_scores" / f"fold_{e:03d}.npz") for e, tr, va in pending)
                    for count, result in enumerate(Parallel(n_jobs=cfg.n_jobs, backend="loky", batch_size=1,
                                            pre_dispatch=cfg.n_jobs, return_as="generator_unordered",
                                            temp_folder=str(run / "logs" / "joblib_temp"))(calls), 1):
                        if count % 10 == 0 or count == len(pending):
                            log(run, f"  {method} K={k} 本批完成 {count}/{len(pending)}；最近折 F1={result.get('validation_macro_f1', float('nan')):.6f}")
                aggregate_classification(run, data, cfg, identity, require_complete=False)
                log(run, f"K={k} 三组结果已落盘（逐折断点及累计 CSV）。")
            # 基线无法安全复用时明确停止，而非在缺失记录下声称完成。
            if any(load_checkpoint(run / "classification" / "checkpoints" / f"full_svm_k20531_{e:03d}", identity) is None for e in range(1, 101)):
                raise RuntimeError("全特征历史结果未能安全复用，需执行显式基线重跑；当前结果未标记完整")
            aggregate_classification(run, data, cfg, identity, require_complete=True)
        if args.phase in ("all", "stability"):
            from ablation_stability import run_stability
            run_stability(run, data, cfg, identity, lambda m: log(run, m))
        if args.phase in ("all", "report"):
            from ablation_results import make_joint_report
            from ablation_visualization import plot_all
            from verify_full_feature_ablation import verify
            make_joint_report(run, cfg)
            plot_all(run)
            checks = verify(run, data, cfg, identity)
            final_summary = read_json(run / "analysis" / "experiment_summary.json")
            final_summary.update(status="complete", verification_checks_passed=checks["checks_passed"],
                                 n_png_figures=7, n_pdf_figures=7)
            atomic_json(run / "analysis" / "experiment_summary.json", final_summary)
            log(run, f"完整验收：{checks['checks_passed']} 项通过；新增/复用拟合数量详见汇总。")
            atomic_json(run / "status.json", {"status": "complete", "elapsed_this_invocation_seconds": time.perf_counter() - start})
            atomic_json(cfg.output_dir / "latest_full_feature_ablation.json", {"run_directory": str(run.relative_to(cfg.output_dir)), "status": "complete"})
        else:
            atomic_json(run / "status.json", {"status": "phase_complete", "phase": args.phase})
        print(f"RESULT_DIRECTORY={run}", flush=True)
        return run
    except BaseException as error:
        atomic_json(run / "status.json", {"status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed", "error": repr(error)})
        (run / "logs" / "error_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        log(run, f"实验停止，已完成断点保留：{error!r}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path, help="恢复原结果目录；严格核对冻结配置与断点哈希")
    parser.add_argument("--n-jobs", type=int, default=1, help="默认1，启动时按当前可用物理内存限制上限")
    parser.add_argument("--phase", choices=("all", "classification", "stability", "report"), default="all")
    run_experiment(parser.parse_args())
