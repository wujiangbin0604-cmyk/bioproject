# -*- coding: utf-8 -*-
"""特征互补性与融合消融入口：31方案、固定开发集、断点恢复、无测试评分。"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from ablation_engine import (atomic_json, build_pipeline, load_checkpoint, read_json, save_checkpoint, scores, sha256)
from baseline import build_baseline
from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from cross_validation import frozen_pipeline_record, make_cv
from data_loader import load_existing_development_data
from full_feature_ablation import hardware, log
from fusion_selection import choose_features, fit_task, prepare_scores, schemes


def parent_identity(cfg, data, run, definitions):
    pointer = read_json(cfg.output_dir / "latest_full_feature_ablation.json")
    parent = cfg.output_dir / pointer["run_directory"]
    old = read_json(parent / "logs" / "frozen_experiment.json")
    old_environment = read_json(parent / "logs" / "environment.json")
    checks = {
        "previous_run_complete": pointer["status"] == "complete" and read_json(parent / "status.json")["status"] == "complete",
        "fixed_split_identical": read_json(parent / "split_manifest.json") == read_json(run / "split_manifest.json"),
        "development_fingerprint_identical": old["development_fingerprint"] == read_json(run / "development_data_record.json")["development_fingerprint_sha256"],
        "all_100_indices_and_order_identical": read_json(parent / "cv_fold_indices.json")["folds"] == definitions,
        "cv_and_model_config_identical": all(old["config"][key] == cfg.to_dict()[key] for key in ("random_state", "cv_mode", "n_splits", "n_repeats", "baseline_c", "max_iter", "tolerance", "class_weight", "numeric_threads")),
        "numeric_versions_identical": all(old_environment["packages"][p] == importlib.metadata.version(p) for p in ("numpy", "pandas", "scikit-learn", "scipy")),
    }
    for method in ("anova_svm", "variance_svm"):
        for k in (20, 50):
            checks[f"pipeline_{method}_{k}_identical"] = frozen_pipeline_record(build_pipeline(cfg, method, k), method, "variance" if method == "variance_svm" else "anova", k) == old["pipelines"][f"{method}_k{k}"]
    record = {"source_directory": str(parent), "source_identity": old["identity"], "checks": checks,
              "classification_reuse_allowed": all(checks.values()),
              "source_files_sha256": {name: sha256(parent / name) for name in ("cv_fold_indices.json", "split_manifest.json", "stability/subsample_indices.csv", "classification/cv_fold_results.csv")}}
    atomic_json(run / "logs" / "reuse_audit.json", record)
    # 索引不符时不重新生成另一套子采样；明确停止以保留用户要求的原协议。
    if not checks["fixed_split_identical"] or not checks["development_fingerprint_identical"] or not checks["all_100_indices_and_order_identical"]:
        raise ValueError("原开发数据或CV索引不一致，不能进行受控配对融合实验")
    return parent, record


def import_single_methods(run, parent, reuse, cfg, data, identity, definitions):
    if not reuse["classification_reuse_allowed"]:
        return 0
    count = 0
    y = data.y
    for rule, old_method in (("anova", "anova_svm"), ("variance", "variance_svm")):
        for k in (20, 50):
            scheme = next(s for s in schemes() if s.name == f"{rule}_k{k}")
            for e, definition in enumerate(definitions, 1):
                target = run / "checkpoints" / f"{scheme.name}_{e:03d}"
                if load_checkpoint(target, identity) is not None:
                    continue
                old_path = parent / "classification" / "checkpoints" / f"{old_method}_k{k}_{e:03d}"
                metadata, arrays = load_checkpoint(old_path, reuse["source_identity"])
                _, cache = load_checkpoint(run / "scores_cv" / f"fold_{e:03d}", identity)
                selected = choose_features(cache["anova_rank"], cache["variance_rank"], rule, k)
                np.testing.assert_array_equal(arrays["selected"], selected)
                metrics = metadata["metrics"]
                for prefix, ids, predicted in (("train", definition["train_sample_ids"], arrays["train_pred"]),
                                                ("validation", definition["validation_sample_ids"], arrays["valid_pred"])):
                    for metric, value in scores(y.loc[ids], predicted).items():
                        np.testing.assert_allclose(metrics[f"{prefix}_{metric}"], value, rtol=1e-12, atol=1e-12)
                assert metadata["audit"]["scaler_fit_audit_passed"] and metadata["audit"]["reserved_test_overlap"] == 0
                row = {**metrics, **asdict(scheme), "scheme": scheme.name, "n_features": k,
                       "status": "evaluated", "result_origin": "verified_prior_fit"}
                ar, vr = np.empty(20531, int), np.empty(20531, int)
                ar[cache["anova_rank"]] = np.arange(1, 20532)
                vr[cache["variance_rank"]] = np.arange(1, 20532)
                audit = {**metadata["audit"], "scheme": scheme.name, "selected_features": k,
                         "selected_indices_match_fold_rule": True, "result_origin": "verified_prior_fit", "source_checkpoint": str(old_path)}
                save_checkpoint(target, {"identity": identity, "metrics": row, "audit": audit,
                                "warnings": metadata["warnings"], "prior_source": str(old_path)},
                                selected=selected, train_pred=arrays["train_pred"], valid_pred=arrays["valid_pred"],
                                anova_score=cache["anova"][selected], variance=cache["variance"][selected], anova_rank=ar[selected], variance_rank=vr[selected])
                count += 1
    return count


def run(args):
    cfg = replace(ExperimentConfig(), cv_mode="repeated", n_jobs=args.n_jobs)
    hw = hardware()
    if not 1 <= cfg.n_jobs <= max(1, int((hw["available_ram_gib"] - .7) / .8)):
        raise MemoryError("n_jobs 超出当前可用内存允许范围；请减少并行进程")
    output = Path(args.resume).resolve() if args.resume else cfg.output_dir / "feature_fusion" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for folder in ("logs", "checkpoints", "scores_cv", "scores_subsamples", "figures", "stability"):
        (output / folder).mkdir(parents=True, exist_ok=True)
    log(output, f"特征融合实验开始/恢复：阶段={args.phase}；n_jobs={cfg.n_jobs}；硬件={hw}")
    atomic_json(cfg.output_dir / "latest_feature_fusion.json", {"run_directory": str(output.relative_to(cfg.output_dir)), "status": "running"})
    atomic_json(output / "status.json", {"status": "running", "phase": args.phase})
    try:
        data = load_existing_development_data(cfg, output, strict_rows_only=True)
        X, y, ids = data.X.to_numpy(dtype=float), data.y.to_numpy(dtype=str), data.X.index.to_numpy(dtype=str)
        assert X.shape == (640, 20531) and data.X.index.equals(data.y.index) and not set(ids) & set(data.reserved_test_ids)
        quality = {"shape": list(X.shape), "duplicate_ids": int(data.X.index.duplicated().sum()), "duplicate_expression_rows": int(data.X.duplicated().sum()),
                   "missing_or_infinite": int((~np.isfinite(X)).sum()), "constant_genes": int((np.ptp(X, axis=0) == 0).sum()),
                   "class_counts": {c: int((y == c).sum()) for c in CLASS_ORDER}}
        atomic_json(output / "logs" / "development_quality.json", quality)
        if quality["duplicate_ids"] or quality["duplicate_expression_rows"] or quality["missing_or_infinite"]:
            raise ValueError("开发集质量检查异常")
        folds = list(make_cv(cfg).split(X, y))
        definitions = []
        for e, (train, valid) in enumerate(folds, 1):
            assert len(train) == 512 and len(valid) == 128 and not set(train) & set(valid)
            definitions.append({"evaluation_id": e, "repeat": (e - 1) // 5 + 1, "fold": (e - 1) % 5 + 1,
                                "train_sample_ids": ids[train].tolist(), "validation_sample_ids": ids[valid].tolist()})
        atomic_json(output / "cv_fold_indices.json", {"cv_mode": "repeated", "folds": definitions})
        parent, reuse = parent_identity(cfg, data, output, definitions)
        frozen = {"protocol": "feature-fusion-v1", "schemes": [asdict(s) for s in schemes()],
                  "rounding": "nearest integer with halves rounded upwards; 75% of 50 = 38; remaining = 12",
                  "development_fingerprint": read_json(output / "development_data_record.json")["development_fingerprint_sha256"],
                  "cv_indices_sha256": sha256(output / "cv_fold_indices.json"),
                  "prior_subsample_indices_sha256": sha256(parent / "stability" / "subsample_indices.csv"),
                  "classifier": frozen_pipeline_record(build_baseline(cfg), "linear_svm", "none", "selected"),
                  "seed": 42, "numeric_threads": cfg.numeric_threads, "no_parameter_search": True,
                  "not_final_model_selection": True, "empty_set_strategy": "record skipped_empty; no imputation or classifier fit",
                  "score_cache": "recomputed from each actual training fold/subsample; bound by full numeric+label digest and ordered IDs",
                  "tie_rules": "ANOVA matches SelectKBest stable descending; variance original position ascending",
                  "versions": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scikit-learn", "scipy")}}
        identity = hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        fp = output / "logs" / "frozen_experiment.json"
        if fp.exists() and read_json(fp)["identity"] != identity:
            raise ValueError("恢复参数、数据、软件版本或划分与原断点不一致")
        atomic_json(fp, {"identity": identity, **frozen})
        # Python3.14的multiprocessing资源跟踪器使用ASCII协议；仅并行临时缓存使用系统英文目录。
        parallel_tmp = Path(tempfile.gettempdir()) / f"rna_fusion_{identity[:16]}"
        if cfg.n_jobs > 1 and not str(parallel_tmp).isascii():
            raise ValueError("系统TEMP路径包含非ASCII字符；请改为--n-jobs 1或设置英文TEMP路径")
        parallel_tmp.mkdir(parents=True, exist_ok=True)
        atomic_json(output / "logs" / "parallel_temporary_directory.json", {"path": str(parallel_tmp), "reason": "Python multiprocessing resource_tracker ASCII protocol"})
        atomic_json(output / "logs" / "environment.json", {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                    "hardware": hw, "n_jobs": cfg.n_jobs, "config": cfg.to_dict(), "packages": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scikit-learn", "scipy", "matplotlib", "joblib", "threadpoolctl")}})
        snapshot = output / "logs" / "source_snapshot" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snapshot.mkdir(parents=True, exist_ok=True)
        names = ("feature_fusion.py", "fusion_selection.py", "fusion_results.py", "fusion_analysis.py", "fusion_visualization.py", "verify_feature_fusion.py", "data_loader.py", "config.py", "baseline.py", "ablation_engine.py")
        for name in names:
            if (PROJECT_DIR / name).exists():
                shutil.copy2(PROJECT_DIR / name, snapshot / name)
        atomic_json(snapshot / "source_sha256.json", {name: sha256(PROJECT_DIR / name) for name in names if (PROJECT_DIR / name).exists()})
        atomic_json(snapshot / "invocation.json", {"phase": args.phase, "n_jobs": cfg.n_jobs, "hardware": hw,
                    "numeric_threads": cfg.numeric_threads, "seed": 42, "identity": identity})
        if args.phase in ("all", "classification"):
            for e, (train, valid) in enumerate(folds, 1):
                prepare_scores(X[train], y[train], output / "scores_cv" / f"fold_{e:03d}", identity, ids[train].tolist())
            count = import_single_methods(output, parent, reuse, cfg, data, identity, definitions)
            log(output, f"核验后导入单方法基线：本次 {count} 个记录；将与融合方案使用同一训练折和原列顺序。")
            for scheme in schemes():
                fit_task(X, y, *folds[0], scheme, 1, cfg, output / "scores_cv" / "fold_001", output / "checkpoints" / f"{scheme.name}_001", identity)
            log(output, "最小流程核验通过：31方案首折、集合大小、匹配M和实际拟合范围均通过，继续完整实验。")
            from fusion_results import aggregate
            for scheme in schemes():
                pending = [(e, tr, va) for e, (tr, va) in enumerate(folds, 1) if load_checkpoint(output / "checkpoints" / f"{scheme.name}_{e:03d}", identity) is None]
                log(output, f"{scheme.name}：待拟合/记录 {len(pending)}/100")
                if not pending:
                    continue
                tasks = (delayed(fit_task)(X, y, tr, va, scheme, e, cfg, output / "scores_cv" / f"fold_{e:03d}",
                         output / "checkpoints" / f"{scheme.name}_{e:03d}", identity) for e, tr, va in pending)
                for i, result in enumerate(Parallel(n_jobs=cfg.n_jobs, backend="loky", batch_size=1, pre_dispatch=cfg.n_jobs,
                                     return_as="generator_unordered", temp_folder=str(parallel_tmp))(tasks), 1):
                    if i % 20 == 0 or i == len(pending):
                        log(output, f"  {scheme.name} 本批 {i}/{len(pending)}；最近F1={result.get('validation_macro_f1')}；特征={result['n_features']}")
                atomic_json(output / "logs" / "progress.json", {"latest_completed_scheme": scheme.name, "n_completed_records": len(list((output / "checkpoints").glob("*.json")))})
            aggregate(output, data, identity)
            log(output, "分类实验和完整逐轮OOF汇总已保存。")
        if args.phase in ("all", "stability"):
            from fusion_results import stability_analysis
            stability_analysis(output, parent, data, identity, lambda s: log(output, s))
        if args.phase in ("all", "report"):
            # 兼容运行中补充的评分诊断表：只从已完成断点重建，不重新拟合。
            if not (output / "fusion_score_diagnostics.csv").exists():
                from fusion_results import aggregate
                aggregate(output, data, identity)
            from fusion_analysis import analyze, write_index
            from fusion_visualization import plot_all
            from verify_feature_fusion import verify
            analyze(output)
            plot_all(output)
            verification = verify(output, data, cfg, identity)
            final_summary = read_json(output / "fusion_experiment_summary.json")
            final_summary.update(status="complete", verification_checks_passed=verification["checks_passed"], n_png_figures=7, n_pdf_figures=7)
            atomic_json(output / "fusion_experiment_summary.json", final_summary)
            write_index(output)
            log(output, f"融合实验验收通过：{verification['checks_passed']}项。")
            atomic_json(output / "status.json", {"status": "complete"})
            atomic_json(cfg.output_dir / "latest_feature_fusion.json", {"run_directory": str(output.relative_to(cfg.output_dir)), "status": "complete"})
        else:
            atomic_json(output / "status.json", {"status": "phase_complete", "phase": args.phase})
        print(f"RESULT_DIRECTORY={output}", flush=True)
    except BaseException as error:
        atomic_json(output / "status.json", {"status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed", "error": repr(error)})
        (output / "logs" / "error_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        error_archive = output / "logs" / "errors"
        error_archive.mkdir(exist_ok=True)
        (error_archive / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".txt")).write_text(traceback.format_exc(), encoding="utf-8")
        log(output, f"失败/中断，完整断点保留：{error!r}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--phase", choices=("all", "classification", "stability", "report"), default="all")
    run(parser.parse_args())
