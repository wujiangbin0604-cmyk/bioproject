# -*- coding: utf-8 -*-
"""三模型硬投票：严格同折预测复用、训练范围审计及可恢复的开发集实验。

默认复用经过数据、索引、参数、哈希和拟合审计核验的已有预测；若任一
基础模型不满足复用条件，则重新运行三个完整 Pipeline，不混配不同划分。
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import time
import traceback

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.utils.validation import check_is_fitted, validate_data

from ablation_engine import (atomic_json, build_pipeline, fit_classification_task,
                             load_checkpoint, read_json, save_checkpoint, sha256)
from baseline import build_baseline
from config import CLASS_ORDER, PROJECT_DIR, ExperimentConfig
from cross_validation import frozen_pipeline_record, make_cv
from data_loader import load_existing_development_data
from fusion_selection import prepare_scores, training_digest

BASE_MODELS = {"A": "anova_svm", "B": "variance_svm", "C": "anova_lr"}
ALL_MODELS = ("A", "B", "C", "vote")
MODEL_NAMES = {"A": "ANOVA Top50 + SVM", "B": "高方差 Top50 + SVM",
               "C": "ANOVA Top50 + LR", "vote": "三模型硬投票"}
BUDGET_CONTROLS = ("union_k50", "anova_matched_union_k50", "variance_matched_union_k50")
METRICS = ("macro_f1", "balanced_accuracy", "accuracy")


def vote_labels(predictions):
    """仅使用三列类别预测；三者均不同时固定采用第一列模型 A。"""
    p = np.asarray(predictions, dtype=str)
    if p.ndim != 2 or p.shape[1] != 3 or not np.isin(p, CLASS_ORDER).all():
        raise ValueError("投票输入必须是 n×3 的五癌种类别数组")
    a, b, c = p.T
    different = (a != b) & (a != c) & (b != c)
    predicted = np.where(b == c, b, a)
    votes = np.sum(p == predicted[:, None], axis=1)
    return predicted, {"has_majority": ~different, "all_three_different": different,
                       "tie_rule_applied": different.copy(), "winning_vote_count": votes,
                       "unanimous": (a == b) & (b == c)}


class ThreeModelHardVotingClassifier(ClassifierMixin, BaseEstimator):
    """sklearn clone 兼容分类器，三个独立 Pipeline，固定等权标签投票。

    estimators=None 时采用本项目已经冻结的 A/B/C 配置；不提供概率接口。
    本次实验采用审计后预测复用，类的 fit 接口供明确授权的新训练使用。
    """
    def __init__(self, estimators=None):
        self.estimators = estimators

    def fit(self, X, y):
        X, y = validate_data(self, X, y, dtype=np.float64)
        configured = self.estimators
        if configured is None:
            cfg = replace(ExperimentConfig(), cv_mode="repeated")
            configured = tuple(build_pipeline(cfg, m, 50) for m in BASE_MODELS.values())
        if len(configured) != 3:
            raise ValueError("必须提供按 A、B、C 顺序排列的三个独立估计器")
        self.classes_ = np.unique(y)
        if set(self.classes_) != set(CLASS_ORDER):
            raise ValueError("该实验分类器只接受既定的五癌种标签")
        self.estimators_ = tuple(clone(model).fit(X, y) for model in configured)
        return self

    def predict_members(self, X):
        check_is_fitted(self, "estimators_")
        X = validate_data(self, X, reset=False, dtype=np.float64)
        return np.column_stack([model.predict(X) for model in self.estimators_])

    def predict(self, X):
        return vote_labels(self.predict_members(X))[0]


def fast_scores(y, pred):
    """由五类混淆矩阵直接计算指标；另一个验收程序使用 sklearn 复核。"""
    labels = np.asarray(CLASS_ORDER)
    lookup = {c: i for i, c in enumerate(labels)}
    a = np.fromiter((lookup[c] for c in y), int)
    b = np.fromiter((lookup[c] for c in pred), int)
    cm = np.bincount(a * 5 + b, minlength=25).reshape(5, 5)
    tp, support, predicted = cm.diagonal(), cm.sum(axis=1), cm.sum(axis=0)
    f1 = np.divide(2 * tp, support + predicted, out=np.zeros(5), where=support + predicted > 0)
    recall = np.divide(tp, support, out=np.zeros(5), where=support > 0)
    return {"macro_f1": float(f1.mean()), "balanced_accuracy": float(recall[support > 0].mean()),
            "accuracy": float(tp.sum() / cm.sum())}


def log(run, message):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    path = run / "logs/progress.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def latest(pointer):
    return PROJECT_DIR / "results" / read_json(PROJECT_DIR / "results" / pointer)["run_directory"]


def definitions(data, cfg):
    ids = data.X.index.to_numpy()
    return {"cv_mode": "repeated", "folds": [
        {"evaluation_id": e, "repeat": (e - 1) // 5 + 1, "fold": (e - 1) % 5 + 1,
         "train_sample_ids": ids[train].tolist(), "validation_sample_ids": ids[valid].tolist()}
        for e, (train, valid) in enumerate(make_cv(cfg).split(data.X, data.y), 1)]}


def pipelines_record(cfg):
    return {f"{method}_k50": frozen_pipeline_record(build_pipeline(cfg, method, 50), method,
            "variance" if key == "B" else "anova", 50) for key, method in BASE_MODELS.items()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_fit_audit(audit):
    """兼容原 Top50 与后续消融实验的等价审计字段，任何缺项均不默认通过。"""
    required = ("pipeline_unfitted_before_fit", "scaler_fit_audit_passed", "classifier_input_is_training_scaled")
    for name in required:
        require(audit.get(name) is True, f"旧拟合审计未通过：{name}")
    for name in ("selector_fit_calls", "scaler_fit_calls", "classifier_fit_calls"):
        require(audit.get(name) == 1, f"旧 fit 次数异常：{name}")
    for name, n in (("train_validation_overlap", 0), ("reserved_test_overlap", 0),
                    ("selector_fit_samples", 512), ("selector_fit_features", 20531),
                    ("scaler_training_samples", 512), ("scaler_features", 50)):
        require(audit.get(name) == n, f"旧审计范围异常：{name}")
    for alternatives in (("selector_input_matches_training", "selector_fit_ids_identical_to_training"),
                         ("selector_scores_match_training_statistics", "selector_training_scores_audit_passed"),
                         ("selected_scores_all_finite", "all_selected_scores_finite")):
        require(any(audit.get(key) is True for key in alternatives), f"旧审计缺失：{alternatives}")


def verify_source(source, data, cfg, folds, dev_hash, pipeline_record):
    """验证三百份断点及逐条 OOF 身份；失败后整个三模型组重新拟合。"""
    frozen = read_json(source / "logs/frozen_experiment.json")
    require(read_json(source / "status.json")["status"] == "complete", "旧消融实验未完成")
    require(read_json(source / "cv_fold_indices.json") == folds, "旧预测不是完全相同的有序划分")
    require(read_json(source / "split_manifest.json") == read_json(cfg.split_manifest_path), "旧开发集清单不同")
    require(frozen["development_fingerprint"] == dev_hash, "旧开发数值/标签/基因顺序不同")
    for key, value in pipeline_record.items():
        require(frozen["pipelines"][key] == value, f"旧模型具体配置不同：{key}")
    old_env = read_json(source / "logs/environment.json")
    for package in ("numpy", "pandas", "scipy", "scikit-learn"):
        require(old_env["packages"][package] == importlib.metadata.version(package), f"环境版本不同：{package}")
    oof = pd.read_csv(source / "classification/oof_predictions.csv")
    oof = oof.loc[oof.k.eq(50) & oof.method.isin(BASE_MODELS.values())].copy()
    require(len(oof) == 38400 and not oof.duplicated(["method", "evaluation_id", "sample_id"]).any(), "旧 OOF 缺失/重复")
    groups = dict(tuple(oof.groupby(["method", "evaluation_id"], sort=False)))
    evidence = []
    for d in folds["folds"]:
        e, tr, va = d["evaluation_id"], d["train_sample_ids"], d["validation_sample_ids"]
        require(not set(tr) & set(va) and not (set(tr) | set(va)) & set(data.reserved_test_ids), "划分泄漏")
        for key, method in BASE_MODELS.items():
            path = source / f"classification/checkpoints/{method}_k50_{e:03d}"
            loaded = load_checkpoint(path, frozen["identity"])
            require(loaded is not None, f"旧断点缺失：{path}")
            record, arrays = loaded
            check_fit_audit(record["audit"])
            row = record["metrics"]
            require((row["evaluation_id"], row["repeat_id"], row["fold_id"]) == (e, d["repeat"], d["fold"]), "旧断点折身份不同")
            require(row.get("convergence_warning_count") == 0, "旧拟合有收敛警告")
            require(len(arrays["selected"]) == len(set(arrays["selected"])) == 50, "旧选中特征不满50")
            require(np.isfinite(arrays["selector_score"]).all(), "旧选中分数非有限")
            group = groups[(method, e)].set_index("sample_id")
            require(set(group.index) == set(va), "旧 OOF 验证样本不一致")
            group = group.loc[va]
            np.testing.assert_array_equal(group.y_true.to_numpy(), data.y.loc[va].to_numpy())
            np.testing.assert_array_equal(group.y_pred.to_numpy(), arrays["valid_pred"])
            require(group.repeat_id.eq(d["repeat"]).all() and group.fold_id.eq(d["fold"]).all(), "OOF轮/折身份不同")
            for part, ids in (("train", tr), ("validation", va)):
                pred = arrays["train_pred" if part == "train" else "valid_pred"]
                require(len(pred) == len(ids) and np.isin(pred, CLASS_ORDER).all(), "预测长度或类别异常")
                for metric, value in fast_scores(data.y.loc[ids], pred).items():
                    np.testing.assert_allclose(row[f"{part}_{metric}"], value, atol=1e-12, rtol=1e-12)
            evidence.append({"model": key, "evaluation_id": e, "source_json": str(path.with_suffix(".json")),
                             "source_json_sha256": sha256(path.with_suffix(".json")),
                             "source_npz_sha256": record["arrays_sha256"], "all_checks_passed": True})
    return frozen, evidence


def verify_budget_source(source, folds, dev_hash, cfg):
    frozen = read_json(source / "logs/frozen_experiment.json")
    require(read_json(source / "status.json")["status"] == "complete", "基因预算实验未完成")
    require(read_json(source / "cv_fold_indices.json") == folds, "预算对照划分不同")
    require(frozen["development_fingerprint"] == dev_hash, "预算对照开发数据不同")
    require(read_json(source / "split_manifest.json") == read_json(cfg.split_manifest_path), "预算对照样本清单不同")
    record = frozen_pipeline_record(build_baseline(cfg), "linear_svm", "none", "selected")
    require(frozen["classifier"] == record, "预算对照分类器/标准化参数不同")
    return frozen


def execute(args):
    cfg = replace(ExperimentConfig(), cv_mode="repeated")
    source = Path(args.source_run).resolve() if args.source_run else latest("latest_full_feature_ablation.json")
    budget_source = Path(args.budget_run).resolve() if args.budget_run else latest("latest_feature_fusion.json")
    run = Path(args.resume).resolve() if args.resume else cfg.output_dir / "hard_voting_ensemble" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run.mkdir(parents=True, exist_ok=True)
    try:
        atomic_json(run / "status.json", {"status": "running", "started": datetime.now().isoformat()})
        log(run, "严格加载已有640名开发患者；保留样本仅检查排除ID，不解析表达或标签。")
        data = load_existing_development_data(cfg, run, strict_rows_only=True)
        X, y = data.X.to_numpy(dtype=float), data.y.to_numpy(dtype=str)
        row_hashes = [hashlib.sha256(np.asarray(row, dtype="<f8").tobytes()).hexdigest() for row in X]
        require(len(set(row_hashes)) == 640, "开发样本存在完全重复表达谱")
        folds = definitions(data, cfg)
        dev_hash = read_json(run / "development_data_record.json")["development_fingerprint_sha256"]
        pipelines = pipelines_record(cfg)
        # 必须先冻结规则，再计算任何投票成绩。
        code_files = ("hard_voting.py", "ensemble_results.py", "ensemble_visualization.py", "verify_hard_voting.py",
                      "config.py", "ablation_engine.py", "feature_selection.py", "variance_topk.py", "data_loader.py",
                      "fusion_selection.py", "cross_validation.py", "baseline.py", "visualization.py", "repeated_cv.py",
                      "ablation_results.py", "ablation_report.py", "evaluation.py", "requirements.txt", "requirements_hard_voting.lock.txt")
        payload = {"protocol": "three-model-hard-vote-v1", "development_fingerprint": dev_hash,
                   "cv": {"class": "RepeatedStratifiedKFold", "n_splits": 5, "n_repeats": 20, "random_state": 42},
                   "pipelines": pipelines, "class_order": list(CLASS_ORDER), "voting": "equal hard labels",
                   "tie_rule": "all three distinct -> A; frozen before vote evaluation", "test_access": False,
                   "source_run": str(source), "source_frozen_sha256": sha256(source / "logs/frozen_experiment.json"),
                   "budget_run": str(budget_source), "force_refit": args.force_refit,
                   "code_hashes": {f: sha256(PROJECT_DIR / f) for f in code_files},
                   "versions": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "joblib", "threadpoolctl", "pillow")}}
        payload["identity"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        frozen_path = run / "logs/frozen_experiment.json"
        if frozen_path.exists():
            require(read_json(frozen_path) == payload, "恢复配置、源码、数据或源记录已改变，请新建运行目录")
        else:
            atomic_json(frozen_path, payload)
        identity = payload["identity"]
        atomic_json(run / "cv_fold_indices.json", folds)
        atomic_json(run / "logs/environment.json", {"python": platform.python_version(), "platform": platform.platform(),
                    "packages": payload["versions"], "numeric_threads": 1,
                    "all_installed_distributions": dict(sorted((d.metadata["Name"], d.version)
                        for d in importlib.metadata.distributions() if d.metadata.get("Name")))})
        for file in code_files:
            dest = run / "source_snapshot" / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_DIR / file, dest)
        source_frozen, evidence, reuse_error = None, [], None
        if not args.force_refit:
            try:
                source_frozen, evidence = verify_source(source, data, cfg, folds, dev_hash, pipelines)
            except (OSError, ValueError, KeyError, AssertionError) as exc:
                reuse_error = f"{type(exc).__name__}: {exc}"
                log(run, f"不能严格复用，三个模型均重新执行完整CV：{reuse_error}")
        reuse = source_frozen is not None
        budget_frozen = verify_budget_source(budget_source, folds, dev_hash, cfg)
        atomic_json(run / "logs/reuse_audit.json", {"reuse_all_base_predictions": reuse,
                    "source_run": str(source), "source_identity": source_frozen["identity"] if reuse else None,
                    "failure_reason": reuse_error, "checked_base_checkpoints": len(evidence),
                    "new_base_fits_required": 0 if reuse else 300, "evidence": evidence,
                    "matched_budget_source_identity": budget_frozen["identity"]})
        if reuse:
            log(run, "300份基础模型断点和38,400条OOF身份全部通过；复用已完成的独立Pipeline拟合。")
        id_pos = {sid: i for i, sid in enumerate(data.X.index)}
        completed = 0
        for d in folds["folds"]:
            e = d["evaluation_id"]
            cp = run / f"checkpoints/fold_{e:03d}"
            tr, va = [np.array([id_pos[s] for s in d[key]], dtype=int) for key in ("train_sample_ids", "validation_sample_ids")]
            # 原排名缓存具有当前训练数值+标签的摘要绑定，既不使用全开发排名，也不碰验证特征。
            score_checkpoint = budget_source / f"scores_cv/fold_{e:03d}"
            cached_scores = load_checkpoint(score_checkpoint, budget_frozen["identity"])
            if cached_scores is None:
                # 缺失时只在新实验目录生成，绝不向旧结果目录补写记录。
                cached_scores = prepare_scores(X[tr], y[tr], run / f"scores_cv/fold_{e:03d}",
                                                identity, d["train_sample_ids"])
            score_record, score_arrays = cached_scores
            require(score_record["training_digest"] == training_digest(X[tr], y[tr]), "训练排名缓存摘要不符")
            require(score_record["sample_ids"] == d["train_sample_ids"], "训练排名缓存有序ID不同")
            require(score_record["independent_score_audit_passed"] is True, "原训练排名缺少独立核验")
            resumed = load_checkpoint(cp, identity)
            if resumed is not None:
                for provenance in resumed[0]["provenance"]:
                    require(sha256(provenance["json"]) == provenance["json_sha256"], "恢复时源元数据改变")
                    require(sha256(provenance["npz"]) == provenance["npz_sha256"], "恢复时源预测改变")
                completed += 1
                continue
            records, arrays_list, provenance, audits = [], [], [], []
            for key, method in BASE_MODELS.items():
                src = source / f"classification/checkpoints/{method}_k50_{e:03d}" if reuse else run / f"base_checkpoints/{method}_k50_{e:03d}"
                if not reuse:
                    fit_classification_task(X, y, tr, va, method, 50, e, cfg, src, identity,
                                            (score_arrays["variance"], score_arrays["anova"], score_arrays["constant"]))
                record, arrays = load_checkpoint(src, source_frozen["identity"] if reuse else identity)
                check_fit_audit(record["audit"])
                rank = score_arrays["variance_rank" if key == "B" else "anova_rank"]
                np.testing.assert_array_equal(arrays["selected"], np.sort(rank[:50]))
                np.testing.assert_allclose(arrays["selector_score"], score_arrays["variance" if key == "B" else "anova"][arrays["selected"]], rtol=1e-6, atol=1e-6)
                records.append(record)
                arrays_list.append(arrays)
                provenance.append({"model": key, "json": str(src.with_suffix(".json")), "json_sha256": sha256(src.with_suffix(".json")),
                                   "npz": str(src.with_suffix(".npz")), "npz_sha256": record["arrays_sha256"]})
                audits.append({"model": key, "evaluation_id": e, "repeat_id": d["repeat"], "fold_id": d["fold"],
                    "reused_fit": reuse, "new_fit_this_run": not reuse, "ordered_indices_verified": True,
                    "OOF_sample_ids_and_true_labels_verified": True, "pipeline_configuration_verified": True,
                    "training_score_digest_verified": True, "selected_genes_match_training_rank": True,
                    "development_fingerprint_verified": True, "reserved_expression_rows_parsed": 0,
                    "reserved_label_rows_parsed": 0, "source_json_sha256": provenance[-1]["json_sha256"], **record["audit"]})
            selected = np.stack([a["selected"] for a in arrays_list])
            np.testing.assert_array_equal(selected[0], selected[2])
            train_predictions = np.column_stack([a["train_pred"] for a in arrays_list])
            valid_predictions = np.column_stack([a["valid_pred"] for a in arrays_list])
            start = time.perf_counter()
            train_vote, train_flags = vote_labels(train_predictions)
            valid_vote, valid_flags = vote_labels(valid_predictions)
            vote_seconds = time.perf_counter() - start
            union = np.unique(selected)
            controls = []
            for name in BUDGET_CONTROLS:
                path = budget_source / f"checkpoints/{name}_{e:03d}"
                cr, ca = load_checkpoint(path, budget_frozen["identity"])
                require(cr["metrics"]["n_features"] == len(union), "单模型预算与投票实际预算不一致")
                expected = union if name == "union_k50" else np.sort(score_arrays["anova_rank" if name.startswith("anova") else "variance_rank"][:len(union)])
                np.testing.assert_array_equal(ca["selected"], expected)
                for audit_name in ("scaler_fit_audit_passed", "scores_independently_audited", "selector_cache_digest_matches_actual_input", "model_input_is_training_scaled"):
                    require(cr["audit"].get(audit_name) is True, f"基因预算对照审计不符：{audit_name}")
                require(cr["audit"]["score_scope_digest"] == score_record["training_digest"], "预算对照的训练数值范围不符")
                require(cr["metrics"]["evaluation_id"] == e and cr["metrics"]["convergence_warning_count"] == 0, "预算对照折号或收敛异常")
                for part, true, pred in (("train", y[tr], ca["train_pred"]), ("validation", y[va], ca["valid_pred"])):
                    for metric, value in fast_scores(true, pred).items():
                        np.testing.assert_allclose(cr["metrics"][f"{part}_{metric}"], value, rtol=1e-12, atol=1e-12)
                controls.append(cr["metrics"])
                provenance.append({"model": name, "json": str(path.with_suffix(".json")), "json_sha256": sha256(path.with_suffix(".json")),
                                   "npz": str(path.with_suffix(".npz")), "npz_sha256": cr["arrays_sha256"]})
            save_checkpoint(cp, {"identity": identity, "evaluation_id": e, "repeat_id": d["repeat"], "fold_id": d["fold"],
                "base_records": records, "audits": audits, "provenance": provenance, "budget_control_metrics": controls,
                "vote_seconds_train_and_validation": vote_seconds, "reused": reuse,
                "score_cache_npz_sha256": score_record["arrays_sha256"], "training_digest": score_record["training_digest"]},
                train_predictions=train_predictions, valid_predictions=valid_predictions, train_vote=train_vote, valid_vote=valid_vote,
                selected=selected, union=union, selector_scores=np.stack([a["selector_score"] for a in arrays_list]),
                **{f"validation_{k}": v for k, v in valid_flags.items()}, **{f"train_{k}": v for k, v in train_flags.items()})
            completed += 1
            if e == 1 or e % 10 == 0:
                log(run, f"完成{e}/100折硬投票及同预算对照审计；没有新增参数搜索。")
        require(completed == 100, "折数不完整")
        from ensemble_results import aggregate, write_report
        from ensemble_visualization import plot_all
        from verify_hard_voting import verify
        summary = aggregate(run, data, identity)
        plot_all(run)
        verification = verify(run)
        write_report(run, summary, verification)
        atomic_json(run / "status.json", {"status": "complete", "completed": datetime.now().isoformat(),
                    "new_base_model_fits": 0 if reuse else 300, "historical_base_model_fits_reused": 300 if reuse else 0,
                    "reserved_test_evaluated": False})
        atomic_json(cfg.output_dir / "latest_hard_voting_ensemble.json", {"run_directory": str(run.relative_to(cfg.output_dir)), "status": "complete"})
        log(run, f"完成；独立验收{verification['checks_passed']}项，结果目录：{run}")
        return run
    except Exception as exc:
        atomic_json(run / "status.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "time": datetime.now().isoformat()})
        log(run, traceback.format_exc())
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", help="包含三组完整预测的旧消融实验目录，默认读取成功指针")
    parser.add_argument("--budget-run", help="同预算单模型旧实验目录，默认读取融合实验成功指针")
    parser.add_argument("--resume", help="恢复同配置目录；哈希或源码变化时拒绝复用")
    parser.add_argument("--force-refit", action="store_true", help="明确重新拟合300个基础模型，仍只使用开发集")
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
