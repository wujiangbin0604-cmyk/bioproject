# -*- coding: utf-8 -*-
"""冻结六方案并进行一次性回顾性保留集评价；不进行任何模型搜索。"""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
import hashlib
import importlib.metadata
import io
import json
import platform
import tarfile
import time
import warnings
from datetime import datetime
from pathlib import Path, PurePosixPath

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import norm
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, confusion_matrix,
                             f1_score, precision_recall_fscore_support)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from ablation_engine import atomic_json, build_pipeline, read_json
from baseline import build_baseline
from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from cross_validation import frozen_pipeline_record
from data_loader import load_existing_development_data
from sklearn.base import clone
from fusion_selection import FusionSelector
from hard_voting import (BASE_MODELS, ThreeModelHardVotingClassifier,
                         pipelines_record as hard_voting_pipelines_record,
                         vote_labels)
from visualization import _save, configure_fonts

MODEL_ORDER = ("M0", "M1", "M2", "M3", "M4", "M5")
MODEL_LABELS = {
    "M0": "M0 全特征",
    "M1": "M1 ANOVA50",
    "M2": "M2 方差20",
    "M3": "M3 ANOVA300",
    "M4": "M4 ANOVA50+方差30",
    "M5": "M5 硬投票",
}
MODEL_COLORS = {
    "M0": "#4C78A8", "M1": "#E45756", "M2": "#72B7B2",
    "M3": "#F2CF5B", "M4": "#B279A2", "M5": "#54A24B",
}
SOURCE_POINTERS = (
    "latest_stage1.json", "latest_full_feature_ablation.json",
    "latest_feature_fusion.json", "latest_hard_voting_ensemble.json",
    "latest_dynamic_arbitration.json",
)
BOOTSTRAP_REPLICATES = 2000
SEED = 42


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def latest_source(pointer_name: str) -> tuple[Path, dict]:
    pointer = read_json(PROJECT_DIR / "results" / pointer_name)
    if pointer.get("status") != "complete":
        raise RuntimeError(f"既有实验未完成：{pointer_name}")
    run = PROJECT_DIR / "results" / pointer["run_directory"]
    return run, pointer


def preflight() -> dict:
    """只审查项目清单、已保存审计和配置；不读取保留集表达值或标签。"""
    split_path = PROJECT_DIR / "data" / "split_manifest.json"
    if not split_path.is_file():
        raise FileNotFoundError("缺少最初固定划分 data/split_manifest.json")
    canonical = read_json(split_path)
    if (len(canonical.get("development_ids", [])) != 640 or
            len(canonical.get("reserved_test_ids", [])) != 161 or
            canonical.get("test_size") != 0.2 or canonical.get("random_state") != 42 or
            canonical.get("test_evaluation_performed") is not False):
        raise RuntimeError("最初的640/161固定划分或未测试标记异常，停止最终评价")
    if set(canonical["development_ids"]) & set(canonical["reserved_test_ids"]):
        raise RuntimeError("固定开发集和保留集ID有交集")

    sources, checks = {}, {}
    for pointer_name in SOURCE_POINTERS:
        run, pointer = latest_source(pointer_name)
        sources[pointer_name] = str(run)
        manifest = read_json(run / "split_manifest.json")
        checks[f"{pointer_name}:same_fixed_split"] = manifest == canonical
        if manifest != canonical:
            raise RuntimeError(f"既有结果划分与最初清单不同：{pointer_name}")
        if pointer_name == "latest_stage1.json":
            stage = read_json(run / "stage_status.json")
            checks["stage1:no_test_evaluation"] = stage.get("test_evaluation_performed") is False
            checks["stage1:all_fold_audits_passed"] = stage.get("all_fold_audits_passed") is True
            if not all((checks["stage1:no_test_evaluation"], checks["stage1:all_fold_audits_passed"])):
                raise RuntimeError("阶段一记录显示测试评价或审计状态不符合要求")
            continue

        status = read_json(run / "status.json")
        checks[f"{pointer_name}:complete"] = status.get("status") == "complete"
        if status.get("status") != "complete":
            raise RuntimeError(f"既有结果状态不是 complete：{pointer_name}")
        if pointer_name == "latest_full_feature_ablation.json":
            frozen = read_json(run / "logs/frozen_experiment.json")
            checks["full_ablation:no_reserved_test_access"] = frozen.get("no_reserved_test_access") is True
            checks["full_ablation:no_hyperparameter_search"] = frozen.get("no_hyperparameter_search") is True
            if not all((checks["full_ablation:no_reserved_test_access"],
                        checks["full_ablation:no_hyperparameter_search"])):
                raise RuntimeError("全特征消融记录无法确认测试隔离或固定配置")
        elif pointer_name == "latest_feature_fusion.json":
            verify = read_json(run / "verification.json")
            frozen = read_json(run / "logs/frozen_experiment.json")
            checks["fusion:verification_passed"] = verify.get("status") == "passed"
            checks["fusion:no_parameter_search"] = frozen.get("no_parameter_search") is True
            schemes = pd.DataFrame(frozen.get("schemes", []))
            add30 = schemes.loc[schemes.name.eq("add_variance_30")]
            checks["fusion:M4_rule_frozen"] = (len(add30) == 1 and
                add30.iloc[0]["rule"] == "add_variance" and int(add30.iloc[0]["k"]) == 50 and
                int(add30.iloc[0]["increment"]) == 30)
            if not all((checks["fusion:verification_passed"], checks["fusion:no_parameter_search"],
                        checks["fusion:M4_rule_frozen"])):
                raise RuntimeError("融合实验审计未通过，或M4配置与add_variance_30不符")
        elif pointer_name == "latest_hard_voting_ensemble.json":
            verify = read_json(run / "verification.json")
            frozen = read_json(run / "logs/frozen_experiment.json")
            checks["hard_vote:verification_passed"] = verify.get("status") == "passed"
            checks["hard_vote:no_test_evaluation"] = status.get("reserved_test_evaluated") is False
            checks["hard_vote:tie_rule_frozen"] = frozen.get("tie_rule") == "all three distinct -> A; frozen before vote evaluation"
            if not all((checks["hard_vote:verification_passed"], checks["hard_vote:no_test_evaluation"],
                        checks["hard_vote:tie_rule_frozen"])):
                raise RuntimeError("硬投票历史审计或冻结平票规则不符合要求")
        elif pointer_name == "latest_dynamic_arbitration.json":
            verify = read_json(run / "verification.json")
            checks["dynamic:verification_passed"] = verify.get("status") == "passed"
            checks["dynamic:no_test_evaluation"] = status.get("reserved_test_evaluated") is False
            if not all((checks["dynamic:verification_passed"], checks["dynamic:no_test_evaluation"])):
                raise RuntimeError("动态仲裁历史审计未通过或保留集曾被评价")

    # 已有文件范围审查：开发集实验的报告明确记录未对161例训练/评分；全样本EDA已披露。
    stage_report = PROJECT_DIR / "results/stage1_baseline/20261015_114512_645762/阶段一结果说明.md"
    report_text = stage_report.read_text(encoding="utf-8") if stage_report.exists() else ""
    checks["historical_full_dataset_eda_disclosed"] = "此前探索性可视化已使用全数据" in report_text
    checks["all_prior_ml_runs_test_evaluation_false"] = all(
        checks.get(key, False) for key in (
            "stage1:no_test_evaluation", "full_ablation:no_reserved_test_access",
            "fusion:verification_passed", "hard_vote:no_test_evaluation",
            "dynamic:no_test_evaluation"))
    if not checks["all_prior_ml_runs_test_evaluation_false"]:
        raise RuntimeError("无法确认先前机器学习实验未使用保留集评分/模型选择，停止评价")
    if not checks["historical_full_dataset_eda_disclosed"]:
        raise RuntimeError("未找到早期全样本EDA暴露记录；不得把保留集视为从未查看")

    # 模型身份、用途和选中特征规则由用户本次要求预先固定。
    full_run, _ = latest_source("latest_full_feature_ablation.json")
    fusion_run, _ = latest_source("latest_feature_fusion.json")
    vote_run, _ = latest_source("latest_hard_voting_ensemble.json")
    full_frozen = read_json(full_run / "logs/frozen_experiment.json")
    vote_frozen = read_json(vote_run / "logs/frozen_experiment.json")
    cfg = ExperimentConfig(cv_mode="repeated")
    expected_records = {
        "anova_svm_k50": frozen_pipeline_record(build_pipeline(cfg, "anova_svm", 50), "anova_svm", "anova", 50),
        "variance_svm_k20": frozen_pipeline_record(build_pipeline(cfg, "variance_svm", 20), "variance_svm", "variance", 20),
        "anova_svm_k300": frozen_pipeline_record(build_pipeline(cfg, "anova_svm", 300), "anova_svm", "anova", 300),
    }
    for key, record in expected_records.items():
        checks[f"configuration:{key}_matches_development_CV"] = full_frozen["pipelines"].get(key) == record
        if not checks[f"configuration:{key}_matches_development_CV"]:
            raise RuntimeError(f"{key}与已完成开发集交叉验证参数不一致")
    current_vote_records = hard_voting_pipelines_record(cfg)
    checks["configuration:M5_all_three_pipelines_match_historical"] = all(
        vote_frozen["pipelines"].get(key) == value for key, value in current_vote_records.items())
    checks["configuration:M5_class_order_matches"] = tuple(vote_frozen["class_order"]) == tuple(CLASS_ORDER)
    if not checks["configuration:M5_all_three_pipelines_match_historical"] or not checks["configuration:M5_class_order_matches"]:
        raise RuntimeError("M5基础模型或类别顺序与已冻结硬投票实验不一致")

    # 核对各方案的100折/20轮开发成绩存在且完整，仅用于开发-测试描述性对照。
    full = pd.read_csv(full_run / "classification/cv_summary.csv")
    for method, k in (("full_svm", 20531), ("anova_svm", 50),
                      ("variance_svm", 20), ("anova_svm", 300)):
        sub = full.loc[full.method.eq(method) & full.k.eq(k)]
        checks[f"development_cv:{method}_{k}_has_100fold_and_20round"] = (
            set(sub.level) == {"validation_fold", "round_oof"} and
            int(sub.loc[sub.level.eq("validation_fold"), "n"].iloc[0]) == 100 and
            int(sub.loc[sub.level.eq("round_oof"), "n"].iloc[0]) == 20)
        if not checks[f"development_cv:{method}_{k}_has_100fold_and_20round"]:
            raise RuntimeError(f"开发集CV记录不完整：{method}, k={k}")
    fusion_summary = pd.read_csv(fusion_run / "fusion_cv_summary.csv")
    m4row = fusion_summary.loc[fusion_summary.scheme.eq("add_variance_30")]
    checks["development_cv:M4_has_100fold_and_20round"] = (
        len(m4row) == 1 and int(m4row.iloc[0].n_evaluated_folds) == 100 and
        int(m4row.iloc[0].n_complete_oof_rounds) == 20 and int(m4row.iloc[0].n_empty_folds) == 0)
    vote_folds = pd.read_csv(vote_run / "ensemble_fold_results.csv")
    vote_rounds = pd.read_csv(vote_run / "ensemble_round_results.csv")
    checks["development_cv:M5_has_100fold_and_20round"] = (
        len(vote_folds.loc[vote_folds.model.eq("vote")]) == 100 and
        len(vote_rounds.loc[vote_rounds.model.eq("vote")]) == 20)
    if not checks["development_cv:M4_has_100fold_and_20round"] or not checks["development_cv:M5_has_100fold_and_20round"]:
        raise RuntimeError("M4或M5开发集结果记录不完整")

    return {"checks": checks, "sources": sources, "split_manifest_sha256": sha256(split_path),
            "development_fingerprint": full_frozen["development_fingerprint"],
            "source_identities": {
                "full_feature_ablation": full_frozen["identity"],
                "feature_fusion": read_json(fusion_run / "logs/frozen_experiment.json")["identity"],
                "hard_voting": vote_frozen["identity"],
            },
            "prior_161_test_prediction_or_score_found": False,
            "historical_full_801_exploratory_visualization_exposure": True,
            "preflight_status": "passed"}


def frozen_pipeline_records(cfg: ExperimentConfig) -> dict:
    base = build_baseline(cfg)
    return {
        "M0": frozen_pipeline_record(base, "full_svm", "none", "all"),
        "M1": frozen_pipeline_record(build_pipeline(cfg, "anova_svm", 50), "anova_svm", "anova", 50),
        "M2": frozen_pipeline_record(build_pipeline(cfg, "variance_svm", 20), "variance_svm", "variance", 20),
        "M3": frozen_pipeline_record(build_pipeline(cfg, "anova_svm", 300), "anova_svm", "anova", 300),
        "M4": {"model_id": "add_variance_30", "selection_rule": "ANOVA Top50 + variance-ranked unselected Top30",
               "rule": "add_variance", "k_anova": 50, "increment_variance": 30,
               "n_unique_genes": 80, "pipeline_steps": ["FusionSelector", "StandardScaler", "LinearSVC"]},
        "M5": {"model_id": "three_model_equal_hard_vote", "members": hard_voting_pipelines_record(cfg),
               "vote": "equal hard labels", "tie_rule": "all three distinct -> A", "probability_output": False},
    }


def freeze_configuration(out: Path, audit: dict, cfg: ExperimentConfig) -> dict:
    records = frozen_pipeline_records(cfg)
    manifest = read_json(cfg.split_manifest_path)
    config = {
        "protocol": "final_fixed_640_dev_161_holdout_once_v1",
        "frozen_at": datetime.now().isoformat(timespec="seconds"),
        "primary_model": "M1",
        "primary_model_rationale": "在读取本次保留集表达值和标签之前，由任务明确指定为主要报告模型。",
        "comparison_roles": {"M0": "主要对照", "M2": "主要对照", "M3": "主要对照",
                             "M4": "探索性扩展对照", "M5": "探索性扩展对照"},
        "models": records,
        "split": {"n_development": 640, "n_reserved_test": 161, "test_size": 0.2,
                  "random_state": 42, "development_ids_sha256": sha256_json(manifest["development_ids"]),
                  "reserved_test_ids_sha256": sha256_json(manifest["reserved_test_ids"]),
                  "manifest_sha256": audit["split_manifest_sha256"]},
        "class_order": list(CLASS_ORDER),
        "reproducibility": {"random_seed": SEED, "macro_f1_stratified_bootstrap_replicates": BOOTSTRAP_REPLICATES,
                            "bootstrap_seed": SEED},
        "selection_and_training": "所有选择器和StandardScaler仅用完整640名开发样本fit；测试标签在全部模型拟合、保存和161例预测输出后才读取。",
        "selection_after_test_forbidden": True,
        "no_retrain_or_model_search_after_test": True,
        "preflight": audit,
        "software": {"python": platform.python_version(), **{
            pkg: importlib.metadata.version(pkg) for pkg in
            ("numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "seaborn", "joblib", "threadpoolctl")}},
        "source_code_sha256": {name: sha256(PROJECT_DIR / name) for name in (
            "final_holdout.py", "config.py", "data_loader.py", "baseline.py", "feature_selection.py",
            "variance_topk.py", "fusion_selection.py", "hard_voting.py", "ablation_engine.py")},
    }
    atomic_json(out / "final_configuration.json", config)
    return config


@contextmanager
def _source_streams(cfg: ExperimentConfig):
    data_path, labels_path = cfg.data_dir / "data.csv", cfg.data_dir / "labels.csv"
    if data_path.is_file() and labels_path.is_file():
        with data_path.open("rb") as xs, labels_path.open("rb") as ys:
            yield ("csv", xs, ys)
        return
    if data_path.exists() != labels_path.exists():
        raise FileNotFoundError("data.csv与labels.csv必须同时存在")
    with tarfile.open(cfg.raw_archive, "r:*") as tar:
        members = {}
        for filename in ("data.csv", "labels.csv"):
            matches = [m for m in tar.getmembers() if m.isfile() and PurePosixPath(m.name).name.lower() == filename]
            if len(matches) != 1:
                raise ValueError(f"压缩包内{filename}成员数量不是1；拒绝猜测文件")
            members[filename] = tar.extractfile(matches[0])
        with members["data.csv"] as xs, members["labels.csv"] as ys:
            yield ("tar", xs, ys)


def read_selected_table(stream, name: str, expected_ids: set[str], selected_ids: list[str],
                        expected_columns: list[str]) -> pd.DataFrame:
    """只将指定样本行交给pandas解析；其它行只读取CSV首字段样本ID。"""
    first = stream.readline()
    header_text = first.decode("utf-8-sig")
    header = next(csv.reader([header_text]))
    if header[1:] != expected_columns or header[0].lower() not in ("", "unnamed: 0", "sample_id", "sample", "id"):
        raise ValueError(f"{name}表头与冻结的样本ID/基因列结构不同，实际前列={header[:5]}")
    if len(header) != len(set(header)):
        raise ValueError(f"{name}表头存在重复列")
    selected = [header_text]
    seen = set()
    for raw in stream:
        id_token = raw.partition(b",")[0].decode("utf-8")
        row_id = next(csv.reader([id_token]))[0]
        if not row_id.startswith("sample_") or row_id in seen:
            raise ValueError(f"{name}存在异常或重复样本ID：{row_id}")
        seen.add(row_id)
        if row_id in selected_ids:
            selected.append(raw.decode("utf-8"))
    if seen != expected_ids or len(selected) != len(selected_ids) + 1:
        raise ValueError(f"{name}样本ID数量/集合与固定划分不符")
    frame = pd.read_csv(io.StringIO("".join(selected)))
    id_col = frame.columns[0]
    frame = frame.set_index(id_col)
    if set(frame.index) != set(selected_ids) or frame.index.has_duplicates:
        raise ValueError(f"{name}选择行的样本ID集合不一致")
    return frame.loc[selected_ids]


def load_test_features_only(cfg: ExperimentConfig, dev_ids: list[str], test_ids: list[str],
                            feature_names: list[str]) -> pd.DataFrame:
    expected = set(dev_ids) | set(test_ids)
    with _source_streams(cfg) as (source_format, xs, _ys):
        frame = read_selected_table(xs, "data.csv", expected, test_ids, feature_names)
    if frame.shape != (len(test_ids), len(feature_names)):
        raise ValueError(f"测试表达矩阵维度异常：{frame.shape}")
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes):
        raise ValueError("测试集包含非数值表达特征")
    values = frame.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("测试表达矩阵包含缺失值或无穷值，停止评分")
    frame.index.name = "sample_id"
    frame.attrs["source_format"] = source_format
    return frame


def load_test_labels_after_prediction(cfg: ExperimentConfig, dev_ids: list[str],
                                      test_ids: list[str]) -> pd.Series:
    expected = set(dev_ids) | set(test_ids)
    with _source_streams(cfg) as (source_format, _xs, ys):
        frame = read_selected_table(ys, "labels.csv", expected, test_ids, ["Class"])
    labels = frame["Class"].astype("string")
    if labels.isna().any() or not set(labels.astype(str)).issubset(set(CLASS_ORDER)):
        raise ValueError("保留集标签缺失或含未知类别")
    labels.index.name = "sample_id"
    labels.name = "cancer_type"
    labels.attrs["source_format"] = source_format
    return labels.astype(str)


def make_models(cfg: ExperimentConfig) -> dict:
    """组装任务预先规定的六个完整方案。"""
    base = build_baseline(cfg)
    m4 = Pipeline([
        ("select", FusionSelector(rule="add_variance", k=50, increment=30)),
        *clone(base).steps,
    ])
    m5 = ThreeModelHardVotingClassifier(estimators=tuple(
        build_pipeline(cfg, method, 50) for method in BASE_MODELS.values()))
    return {
        "M0": base,
        "M1": build_pipeline(cfg, "anova_svm", 50),
        "M2": build_pipeline(cfg, "variance_svm", 20),
        "M3": build_pipeline(cfg, "anova_svm", 300),
        "M4": m4,
        "M5": m5,
    }


def get_pipeline_members(model_id: str, model) -> list[tuple[str, Pipeline]]:
    if model_id != "M5":
        return [(model_id, model)]
    return [(f"M5_{name}", estimator) for name, estimator in zip("ABC", model.estimators_)]


def extract_feature_records(model_id: str, model, feature_names: list[str]) -> tuple[list[dict], int]:
    """提取最终fit得到的基因名单及选择依据；不读取测试标签。"""
    records: list[dict] = []
    unique_genes: set[str] = set()
    for member_id, pipeline in get_pipeline_members(model_id, model):
        selector = pipeline.named_steps.get("select")
        if selector is None:
            indices = np.arange(len(feature_names), dtype=int)
            reasons = {int(i): "全部原始基因" for i in indices}
            score_map = {}
            anova_rank_map, variance_rank_map = {}, {}
        elif isinstance(selector, FusionSelector):
            indices = np.asarray(selector.selected_indices_, dtype=int)
            top_anova = set(selector.anova_rank_[:50].tolist())
            reasons = {int(i): ("ANOVA排名Top50" if i in top_anova else "高方差排名中未入选ANOVA者补充Top30")
                       for i in indices}
            score_map = {}
            anova_rank_map = {int(g): int(i + 1) for i, g in enumerate(selector.anova_rank_)}
            variance_rank_map = {int(g): int(i + 1) for i, g in enumerate(selector.variance_rank_)}
        else:
            indices = np.flatnonzero(selector.get_support()).astype(int)
            if selector.__class__.__name__ == "VarianceTopK":
                reasons = {int(i): "训练集原表达方差TopK" for i in indices}
                score_map = {int(i): float(selector.variances_[i]) for i in indices}
            else:
                reasons = {int(i): "训练集五分类ANOVA F-score TopK" for i in indices}
                score_map = {int(i): float(selector.scores_[i]) for i in indices}
            anova_rank_map, variance_rank_map = {}, {}
        expected = 20531 if model_id == "M0" else (80 if model_id == "M4" else 50 if member_id.startswith("M5_") else 20 if model_id == "M2" else 300 if model_id == "M3" else 50)
        if len(indices) != expected or len(set(indices.tolist())) != expected:
            raise AssertionError(f"{member_id}实际特征数错误：{len(indices)} != {expected}")
        for rank, idx in enumerate(indices, start=1):
            gene = str(feature_names[int(idx)])
            unique_genes.add(gene)
            records.append({
                "model": model_id, "member": member_id, "feature_index": int(idx), "gene_id": gene,
                "selected_order": rank, "selection_reason": reasons[int(idx)],
                "selection_score": score_map.get(int(idx), np.nan),
                "anova_rank": anova_rank_map.get(int(idx), np.nan),
                "variance_rank": variance_rank_map.get(int(idx), np.nan),
            })
    return records, len(unique_genes)


def audit_fitted_model(model_id: str, model, expected_samples: int) -> list[dict]:
    records = []
    for member_id, pipeline in get_pipeline_members(model_id, model):
        scaler = pipeline.named_steps["scale"]
        selector = pipeline.named_steps.get("select")
        estimator = pipeline.named_steps["model"]
        n_selected = int(scaler.n_features_in_)
        selector_samples = (int(selector.n_samples_seen_) if hasattr(selector, "n_samples_seen_") else expected_samples) if selector is not None else expected_samples
        checks = {
            "fit_samples": int(scaler.n_samples_seen_),
            "selector_fit_samples": selector_samples,
            "scaler_fit_samples": int(scaler.n_samples_seen_),
            "scaler_fit_features": n_selected,
            "classifier_fit_features": int(estimator.n_features_in_),
            "selector_fit_features": int(selector.n_features_in_) if selector is not None else 20531,
            "reserved_test_fit_samples": 0,
            "development_ids_only": True,
            "train_test_id_overlap": 0,
            "scaler_is_after_selector": list(pipeline.named_steps).index("scale") > list(pipeline.named_steps).index("select") if selector is not None else True,
        }
        if (checks["fit_samples"] != expected_samples or checks["selector_fit_samples"] != expected_samples or
                checks["scaler_fit_samples"] != expected_samples or checks["classifier_fit_features"] != n_selected or
                checks["selector_fit_features"] != 20531):
            raise AssertionError(f"{member_id}拟合范围审计失败：{checks}")
        if selector is not None and not checks["scaler_is_after_selector"]:
            raise AssertionError(f"{member_id}的StandardScaler不在选择器之后")
        records.append({"model": model_id, "member": member_id, **checks})
    return records


def collect_development_metrics(sources: dict) -> pd.DataFrame:
    full = pd.read_csv(Path(sources["latest_full_feature_ablation.json"]) / "classification/cv_summary.csv")
    fusion = pd.read_csv(Path(sources["latest_feature_fusion.json"]) / "fusion_cv_summary.csv")
    vote_fold = pd.read_csv(Path(sources["latest_hard_voting_ensemble.json"]) / "ensemble_fold_results.csv")
    vote_round = pd.read_csv(Path(sources["latest_hard_voting_ensemble.json"]) / "ensemble_round_results.csv")
    definitions = {
        "M0": ("full_svm", 20531), "M1": ("anova_svm", 50),
        "M2": ("variance_svm", 20), "M3": ("anova_svm", 300),
    }
    output = []
    for model_id, (method, k) in definitions.items():
        rows = full.loc[full.method.eq(method) & full.k.eq(k)]
        fold, rounds = rows.loc[rows.level.eq("validation_fold")].iloc[0], rows.loc[rows.level.eq("round_oof")].iloc[0]
        output.append({
            "model": model_id,
            "development_macro_f1_100fold_mean": float(fold.validation_macro_f1_mean),
            "development_macro_f1_100fold_sd": float(fold.validation_macro_f1_std),
            "development_balanced_accuracy_100fold_mean": float(fold.validation_balanced_accuracy_mean),
            "development_balanced_accuracy_100fold_sd": float(fold.validation_balanced_accuracy_std),
            "development_accuracy_100fold_mean": float(fold.validation_accuracy_mean),
            "development_macro_f1_20round_oof_mean": float(rounds.oof_macro_f1_mean),
            "development_macro_f1_20round_oof_sd": float(rounds.oof_macro_f1_std),
            "development_balanced_accuracy_20round_oof_mean": float(rounds.oof_balanced_accuracy_mean),
            "development_accuracy_20round_oof_mean": float(rounds.oof_accuracy_mean),
        })
    m4 = fusion.loc[fusion.scheme.eq("add_variance_30")].iloc[0]
    output.append({
        "model": "M4",
        "development_macro_f1_100fold_mean": float(m4.validation_macro_f1_mean),
        "development_macro_f1_100fold_sd": float(m4.validation_macro_f1_std),
        "development_balanced_accuracy_100fold_mean": float(m4.validation_balanced_accuracy_mean),
        "development_balanced_accuracy_100fold_sd": float(m4.validation_balanced_accuracy_std),
        "development_accuracy_100fold_mean": float(m4.validation_accuracy_mean),
        "development_macro_f1_20round_oof_mean": float(m4.oof_macro_f1_mean),
        "development_macro_f1_20round_oof_sd": float(m4.oof_macro_f1_std),
        "development_balanced_accuracy_20round_oof_mean": float(m4.oof_balanced_accuracy_mean),
        "development_accuracy_20round_oof_mean": float(m4.oof_accuracy_mean),
    })
    vf, vr = vote_fold.loc[vote_fold.model.eq("vote")], vote_round.loc[vote_round.model.eq("vote")]
    output.append({
        "model": "M5",
        "development_macro_f1_100fold_mean": float(vf.validation_macro_f1.mean()),
        "development_macro_f1_100fold_sd": float(vf.validation_macro_f1.std(ddof=1)),
        "development_balanced_accuracy_100fold_mean": float(vf.validation_balanced_accuracy.mean()),
        "development_balanced_accuracy_100fold_sd": float(vf.validation_balanced_accuracy.std(ddof=1)),
        "development_accuracy_100fold_mean": float(vf.validation_accuracy.mean()),
        "development_macro_f1_20round_oof_mean": float(vr.oof_macro_f1.mean()),
        "development_macro_f1_20round_oof_sd": float(vr.oof_macro_f1.std(ddof=1)),
        "development_balanced_accuracy_20round_oof_mean": float(vr.oof_balanced_accuracy.mean()),
        "development_accuracy_20round_oof_mean": float(vr.oof_accuracy.mean()),
    })
    result = pd.DataFrame(output).set_index("model").loc[list(MODEL_ORDER)].reset_index()
    result["model_name"] = result["model"].map(MODEL_LABELS)
    return result


def wilson_interval(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    z = float(norm.ppf(1 - alpha / 2))
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return float(max(0, center - half)), float(min(1, center + half))


def stratified_bootstrap_macro_f1(y: np.ndarray, prediction: np.ndarray, replicates: int,
                                  seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    by_class = [np.flatnonzero(y == label) for label in CLASS_ORDER]
    scores = np.empty(replicates, dtype=float)
    for i in range(replicates):
        indices = np.concatenate([rng.choice(idx, size=len(idx), replace=True) for idx in by_class])
        scores[i] = f1_score(y[indices], prediction[indices], labels=CLASS_ORDER,
                             average="macro", zero_division=0)
    return tuple(float(x) for x in np.quantile(scores, [0.025, 0.975]))


def calculate_outputs(out: Path, configuration: dict, dev_metrics: pd.DataFrame,
                      y_test: pd.Series, prediction_table: pd.DataFrame,
                      selected_feature_table: pd.DataFrame, unique_gene_counts: dict,
                      fit_audits: list[dict], warnings_by_model: dict,
                      model_paths: dict, run_times: dict) -> dict:
    y = y_test.to_numpy(dtype=str)
    perclass_rows, confusion_rows, error_rows, summary_rows = [], [], [], []
    prediction_columns = {m: prediction_table[f"pred_{m}"].to_numpy(dtype=str) for m in MODEL_ORDER}
    for model_id in MODEL_ORDER:
        pred = prediction_columns[model_id]
        acc = float(accuracy_score(y, pred))
        macro = float(f1_score(y, pred, labels=CLASS_ORDER, average="macro", zero_division=0))
        bal = float(balanced_accuracy_score(y, pred))
        nerr = int(np.sum(pred != y))
        ci_acc = wilson_interval(int(np.sum(pred == y)), len(y))
        ci_f1 = stratified_bootstrap_macro_f1(y, pred, BOOTSTRAP_REPLICATES, SEED)
        precision, recall, f1, support = precision_recall_fscore_support(
            y, pred, labels=CLASS_ORDER, zero_division=0)
        for cls, p, r, f, n in zip(CLASS_ORDER, precision, recall, f1, support):
            perclass_rows.append({"model": model_id, "model_name": MODEL_LABELS[model_id],
                                  "cancer_type": cls, "precision": float(p), "recall": float(r),
                                  "f1": float(f), "support": int(n)})
        matrix = confusion_matrix(y, pred, labels=CLASS_ORDER)
        for i, true_cls in enumerate(CLASS_ORDER):
            for j, pred_cls in enumerate(CLASS_ORDER):
                confusion_rows.append({"model": model_id, "true_class": true_cls,
                                       "predicted_class": pred_cls, "count": int(matrix[i, j])})
        for index in np.flatnonzero(pred != y):
            error_rows.append({"model": model_id, "sample_id": str(y_test.index[index]),
                               "true_label": str(y[index]), "predicted_label": str(pred[index])})
        devrow = dev_metrics.loc[dev_metrics.model.eq(model_id)].iloc[0]
        summary_rows.append({
            "model": model_id, "model_name": MODEL_LABELS[model_id],
            "n_test": int(len(y)), "n_errors": nerr, "n_correct": int(len(y)-nerr),
            "accuracy": acc, "accuracy_wilson95_low": ci_acc[0], "accuracy_wilson95_high": ci_acc[1],
            "macro_f1": macro, "macro_f1_stratified_bootstrap95_low": ci_f1[0],
            "macro_f1_stratified_bootstrap95_high": ci_f1[1], "balanced_accuracy": bal,
            "n_unique_genes": int(unique_gene_counts[model_id]),
            "fit_seconds": float(run_times[model_id]["fit_seconds"]),
            "predict_seconds": float(run_times[model_id]["predict_seconds"]),
            "development_macro_f1_100fold_mean": devrow.development_macro_f1_100fold_mean,
            "development_macro_f1_20round_oof_mean": devrow.development_macro_f1_20round_oof_mean,
            "development_balanced_accuracy_100fold_mean": devrow.development_balanced_accuracy_100fold_mean,
            "test_minus_development_macro_f1_100fold": macro - devrow.development_macro_f1_100fold_mean,
            "test_minus_development_macro_f1_20round_oof": macro - devrow.development_macro_f1_20round_oof_mean,
            "test_minus_development_balanced_accuracy_100fold": bal - devrow.development_balanced_accuracy_100fold_mean,
            "convergence_warnings": json.dumps(warnings_by_model[model_id], ensure_ascii=False),
            "pipeline_file": str(model_paths[model_id].relative_to(out)),
        })
    summary = pd.DataFrame(summary_rows).set_index("model").loc[list(MODEL_ORDER)].reset_index()
    perclass = pd.DataFrame(perclass_rows)
    confusion = pd.DataFrame(confusion_rows)
    errors = pd.DataFrame(error_rows, columns=["model", "sample_id", "true_label", "predicted_label"])
    development_vs_test = dev_metrics.merge(summary, on=["model", "model_name"], how="left", validate="one_to_one")
    write_csv(summary, out / "final_test_summary.csv")
    write_csv(perclass, out / "final_test_per_class_metrics.csv")
    write_csv(prediction_table, out / "final_test_predictions.csv")
    write_csv(errors, out / "final_test_errors.csv")
    write_csv(confusion, out / "final_confusion_matrices.csv")
    write_csv(selected_feature_table, out / "final_selected_features.csv")
    write_csv(development_vs_test, out / "development_vs_test.csv")

    # 错误共现采用161个样本ID做集合交集，未将错误计数解释为独立试验。
    error_sets = {m: set(errors.loc[errors.model.eq(m), "sample_id"].astype(str)) for m in MODEL_ORDER}
    overlap = pd.DataFrame(index=MODEL_ORDER, columns=MODEL_ORDER, dtype=int)
    overlap_rows = []
    for a in MODEL_ORDER:
        for b in MODEL_ORDER:
            count = len(error_sets[a] & error_sets[b])
            overlap.loc[a, b] = count
            overlap_rows.append({"model_a": a, "model_b": b, "shared_error_sample_count": count})
    overlap_df = pd.DataFrame(overlap_rows)
    write_csv(overlap_df, out / "final_error_overlap.csv")
    pattern = prediction_table.copy()
    for m in MODEL_ORDER:
        pattern[f"error_{m}"] = pattern[f"pred_{m}"].astype(str).ne(pattern["y_true"].astype(str))
    pattern["error_pattern"] = pattern.apply(lambda row: "+".join(m for m in MODEL_ORDER if row[f"error_{m}"]) or "无模型错误", axis=1)
    pattern_summary = pattern.groupby("error_pattern", as_index=False).agg(n_samples=("sample_id", "count"))
    write_csv(pattern_summary.sort_values("n_samples", ascending=False), out / "final_error_patterns.csv")
    change_rows = []
    for model_id in ("M4", "M5"):
        pred = prediction_columns[model_id]
        p1 = prediction_columns["M1"]
        for i in range(len(y)):
            m1_correct, model_correct = p1[i] == y[i], pred[i] == y[i]
            if m1_correct != model_correct:
                change_rows.append({"comparison": f"{model_id}_vs_M1", "sample_id": str(y_test.index[i]),
                                    "true_label": str(y[i]), "M1_prediction": str(p1[i]),
                                    f"{model_id}_prediction": str(pred[i]),
                                    "change": "纠正M1错误" if model_correct else "新增错误"})
    changes = pd.DataFrame(change_rows, columns=["comparison", "sample_id", "true_label", "M1_prediction", "M4_prediction", "M5_prediction", "change"])
    # 每条比较只填写适用的一个模型预测列，另一个模型列为空。
    write_csv(changes, out / "final_M4_M5_error_changes_vs_M1.csv")

    # 需先把M5是否全体一致及固定平票规则的审计结果另存。
    m5_all = prediction_table["M5_all_three_different"].astype(bool)
    m5_unanimous = prediction_table["M5_unanimous"].astype(bool)
    vote_audit = {"M5_unanimous_predictions": int(m5_unanimous.sum()),
                  "M5_all_three_different": int(m5_all.sum()),
                  "M5_tie_rule_applied": int(prediction_table["M5_tie_rule_applied"].astype(bool).sum()),
                  "M5_tie_rule_predictions_equal_member_A": bool(
                      prediction_table.loc[m5_all, "pred_M5"].astype(str).eq(
                          prediction_table.loc[m5_all, "M5_member_A"].astype(str)).all())}
    atomic_json(out / "m5_vote_rule_audit.json", vote_audit)
    n_with_multiple_errors = int((pattern[[f"error_{m}" for m in MODEL_ORDER]].sum(axis=1) >= 2).sum())
    return {"summary": summary, "perclass": perclass, "confusion": confusion,
            "errors": errors, "error_overlap": overlap, "error_patterns": pattern_summary,
            "error_changes": changes, "development_vs_test": development_vs_test,
            "n_samples_with_multiple_model_errors": n_with_multiple_errors,
            "vote_audit": vote_audit}


def plot_all(out: Path, tables: dict) -> None:
    figures = out / "figures"
    configure_fonts()
    devtest = tables["development_vs_test"].set_index("model").loc[list(MODEL_ORDER)]
    summary = tables["summary"].set_index("model").loc[list(MODEL_ORDER)]
    perclass = tables["perclass"]
    x = np.arange(len(MODEL_ORDER))
    short = [MODEL_LABELS[m] for m in MODEL_ORDER]

    for metric, dev_col, round_col, test_col, title, filename in (
        ("Macro-F1", "development_macro_f1_100fold_mean", "development_macro_f1_20round_oof_mean", "macro_f1",
         "开发集与回顾性保留集 Macro-F1", "01_开发集与测试集_MacroF1"),
        ("Balanced Accuracy", "development_balanced_accuracy_100fold_mean", "development_balanced_accuracy_20round_oof_mean", "balanced_accuracy",
         "开发集与回顾性保留集 Balanced Accuracy", "02_开发集与测试集_BalancedAccuracy"),
    ):
        fig, ax = plt.subplots(figsize=(11, 5.6), layout="constrained")
        width = .24
        for j, (label, col, color) in enumerate((
            ("开发集100折均值", dev_col, "#7B8DA6"),
            ("开发集20轮完整OOF均值", round_col, "#9EB7A6"),
            ("161例保留集", test_col, "#D86F63"),
        )):
            vals = devtest.loc[MODEL_ORDER, col].to_numpy(dtype=float)
            ax.bar(x + (j-1)*width, vals, width=width, color=color, label=label)
        ax.set_xticks(x, short, rotation=20, ha="right")
        ymin = max(0.0, min(float(devtest[dev_col].min()), float(devtest[round_col].min()), float(devtest[test_col].min())) - .02)
        ax.set_ylim(ymin, 1.01)
        ax.set_ylabel(metric)
        ax.set_title(title)
        ax.grid(axis="y", color="#E6E9ED", linewidth=.7)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, ncol=3, loc="lower right")
        fig.text(.5, -.01, "重复交叉验证为开发集描述性结果；保留集为单次回顾性评价，误差线不表示模型间显著性。",
                 ha="center", fontsize=9)
        _save(fig, figures, filename)

    fig, ax = plt.subplots(figsize=(10.5, 5.5), layout="constrained")
    width = .24
    for j, (metric, color) in enumerate((
        ("macro_f1", "#4C78A8"), ("balanced_accuracy", "#F2A541"), ("accuracy", "#55A868"))):
        vals = summary.loc[MODEL_ORDER, metric].to_numpy(dtype=float)
        ax.bar(x+(j-1)*width, vals, width=width, color=color, label=metric.replace("_", " "))
    ax.set_xticks(x, short, rotation=20, ha="right")
    ymin = max(0, float(summary[["macro_f1", "balanced_accuracy", "accuracy"]].min().min()) - .03)
    ax.set_ylim(ymin, 1.01)
    ax.set_ylabel("测试集指标")
    ax.set_title("六个冻结方案的保留集分类性能")
    ax.grid(axis="y", color="#E6E9ED", linewidth=.7); ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3)
    _save(fig, figures, "03_六模型测试集性能")

    labels = list(CLASS_ORDER)
    matrix = tables["confusion"].loc[tables["confusion"].model.eq("M1")].pivot(
        index="true_class", columns="predicted_class", values="count").reindex(index=labels, columns=labels)
    fig, ax = plt.subplots(figsize=(7.2, 6.2), layout="constrained")
    sns.heatmap(matrix, annot=True, fmt="d", cmap="Blues", cbar_kws={"label": "样本数"},
                linewidths=.5, linecolor="white", ax=ax)
    ax.set(xlabel="预测类别", ylabel="真实类别", title="主要报告模型 M1：保留集混淆矩阵")
    _save(fig, figures, "04_M1五类别混淆矩阵")

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.0), layout="constrained", sharex=True)
    for ax, metric in zip(axes, ("precision", "recall", "f1")):
        for model_id in MODEL_ORDER:
            sub = perclass.loc[perclass.model.eq(model_id)].set_index("cancer_type").reindex(labels)
            ax.plot(labels, sub[metric], marker="o", markersize=3.8, linewidth=1.3,
                    color=MODEL_COLORS[model_id], label=model_id)
        vals = perclass[metric].to_numpy(dtype=float)
        ax.set_ylim(max(0, vals.min() - .04), 1.01)
        ax.set_title(metric.capitalize())
        ax.set_ylabel("指标值")
        ax.tick_params(axis="x", rotation=35)
        ax.grid(axis="y", color="#E6E9ED", linewidth=.7); ax.set_axisbelow(True)
    axes[-1].legend(frameon=False, bbox_to_anchor=(1.03, 1), loc="upper left", title="冻结方案")
    fig.suptitle("六个方案的分癌种 Precision、Recall 与 F1")
    _save(fig, figures, "05_各癌种分类指标")

    overlap = tables["error_overlap"].reindex(index=MODEL_ORDER, columns=MODEL_ORDER)
    fig, ax = plt.subplots(figsize=(7.4, 6.3), layout="constrained")
    sns.heatmap(overlap, annot=True, fmt="d", cmap="Reds", square=True, linewidths=.5,
                cbar_kws={"label": "共同误分类样本数"}, ax=ax)
    ax.set(xticklabels=MODEL_ORDER, yticklabels=MODEL_ORDER,
           title="模型错误样本重合（对角线为本模型错误数）", xlabel="模型", ylabel="模型")
    _save(fig, figures, "06_模型错误样本重合")

    fig, ax = plt.subplots(figsize=(9.5, 6.0), layout="constrained")
    for model_id in MODEL_ORDER:
        row = summary.loc[model_id]
        ax.scatter(row.n_unique_genes, row.macro_f1, s=75, marker="o", color=MODEL_COLORS[model_id], label=f"{model_id} Macro-F1")
        ax.scatter(row.n_unique_genes, row.balanced_accuracy, s=75, marker="s", facecolors="none",
                   edgecolors=MODEL_COLORS[model_id], label=f"{model_id} Balanced Acc.")
        ax.annotate(model_id, (row.n_unique_genes, row.macro_f1), xytext=(5, 5), textcoords="offset points", fontsize=8)
    ax.set_xscale("log")
    ax.set(xlabel="实际不同基因数（对数坐标；M5按三模型并集）", ylabel="161例保留集性能",
           title="实际特征预算与保留集分类性能")
    ax.set_ylim(max(0, float(summary[["macro_f1", "balanced_accuracy"]].min().min())-.03), 1.01)
    ax.grid(color="#E6E9ED", linewidth=.7); ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=2, fontsize=8, loc="lower right")
    _save(fig, figures, "07_特征数量与测试集性能")


def _markdown_table(frame: pd.DataFrame, columns: list[str] | None = None, digits: int = 5) -> str:
    view = frame[columns].copy() if columns else frame.copy()
    def fmt(v):
        if pd.isna(v): return ""
        if isinstance(v, (float, np.floating)): return f"{float(v):.{digits}f}"
        return str(v)
    headers = list(view.columns)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"]*len(headers)) + " |"]
    lines.extend("| " + " | ".join(fmt(v) for v in row) + " |" for row in view.itertuples(index=False, name=None))
    return "\n".join(lines)


def write_reports(out: Path, tables: dict, stability: pd.DataFrame,
                  audit: dict, configuration: dict) -> None:
    summary = tables["summary"]
    devtest = tables["development_vs_test"]
    perclass = tables["perclass"]
    errors = tables["errors"]
    changes = tables["error_changes"]
    m1 = summary.loc[summary.model.eq("M1")].iloc[0]
    best_single = summary.loc[summary.model.isin(["M0", "M1", "M2", "M3", "M4"])].sort_values("macro_f1", ascending=False).iloc[0]
    m5 = summary.loc[summary.model.eq("M5")].iloc[0]
    m4 = summary.loc[summary.model.eq("M4")].iloc[0]
    m2 = summary.loc[summary.model.eq("M2")].iloc[0]
    m0 = summary.loc[summary.model.eq("M0")].iloc[0]
    m3 = summary.loc[summary.model.eq("M3")].iloc[0]
    corrections = {key: {change: int(((changes.comparison == f"{key}_vs_M1") & (changes.change == change)).sum())
                         for change in ("纠正M1错误", "新增错误")} for key in ("M4", "M5")}
    perclass_matrix = perclass.pivot(index="cancer_type", columns="model", values="f1").reindex(index=CLASS_ORDER, columns=MODEL_ORDER)
    class_drops = []
    for model_id in MODEL_ORDER:
        lower = [c for c in CLASS_ORDER if perclass_matrix.loc[c, model_id] < perclass_matrix.loc[c, "M1"] - 1e-12]
        class_drops.append(f"{model_id}：{('、'.join(lower) if lower else '无类别F1低于M1')}")
    err_by_class = errors.merge(tables["perclass"][["model", "cancer_type", "support"]].drop_duplicates(),
                                left_on=["model", "true_label"], right_on=["model", "cancer_type"], how="left")
    _ = err_by_class
    acc_ci = (m1.accuracy_wilson95_low, m1.accuracy_wilson95_high)
    matrix = tables["confusion"].loc[tables["confusion"].model.eq("M1")].pivot(
        index="true_class", columns="predicted_class", values="count").reindex(index=CLASS_ORDER, columns=CLASS_ORDER)
    stability50 = stability.loc[stability.k.eq(50)].set_index("method")
    stability_table = stability.loc[stability.k.eq(50), ["method", "n_sets", "n_pairs", "jaccard_mean", "jaccard_std", "kuncheva_mean", "n_always_selected", "n_ever_selected"]].copy()
    overlap_events = int(tables["n_samples_with_multiple_model_errors"])
    m5_vs_best = float(m5.macro_f1 - best_single.macro_f1)

    report = f"""# 五癌种基因表达分类：回顾性保留测试集评价

## 评价边界与冻结方案

最终评价使用最初固定的640名开发样本和161名保留样本，没有重新划分。先前完成的阶段一、RQ1/RQ2/RQ3消融、特征融合、硬投票和动态仲裁记录均能对齐同一划分，既有审计未发现保留集进入训练、特征选择、调参、预测评分或模型选择。本次前置审计通过{sum(bool(x) for x in audit['checks'].values())}项检查。六个方案及主要模型身份在读取保留集表达值和标签前写入 `final_configuration.json`；M1是任务预先指定的主要报告模型，M0/M2/M3为主要对照，M4/M5为探索性扩展。

本次只在640名开发样本上重新拟合最终Pipeline。ANOVA、高方差排名、标准化和分类器均只使用开发样本；随后对161例统一预测，并将预测保存后才读取这161例标签。每个方案的独立基因数、训练范围和模型文件见 `final_selected_features.csv`、`final_evaluation_audit.json` 和 `models/`。

需要披露：此前项目曾对全体801例进行探索性可视化。因此，这161例没有参与既有机器学习模型评分或选择，也没有参与本轮拟合，但不是研究全过程从未查看的独立外部队列。本报告按“回顾性保留集评价”解释结果。

## 六模型测试集结果

Accuracy区间为95% Wilson二项区间。Macro-F1区间使用2000次按真实癌种分层、每层有放回抽取原支持数的患者级bootstrap百分位区间（随机种子42）；它描述当前161例的抽样不确定性，不代表跨医院或跨平台的外部区间。

{_markdown_table(summary[['model','n_test','n_errors','n_unique_genes','accuracy','accuracy_wilson95_low','accuracy_wilson95_high','macro_f1','macro_f1_stratified_bootstrap95_low','macro_f1_stratified_bootstrap95_high','balanced_accuracy']], digits=6)}

主要报告模型M1的Accuracy为{m1.accuracy:.6f}（Wilson 95% CI {acc_ci[0]:.6f}–{acc_ci[1]:.6f}），Macro-F1为{m1.macro_f1:.6f}（分层bootstrap 95% CI {m1.macro_f1_stratified_bootstrap95_low:.6f}–{m1.macro_f1_stratified_bootstrap95_high:.6f}），Balanced Accuracy为{m1.balanced_accuracy:.6f}。保留集共161例；完整逐样本结果见CSV。

## 开发集与保留集对照

开发集100折结果是相关重复交叉验证的描述统计；20轮OOF重复同一批开发患者。两者均不是独立测试样本，不能按100个折进行显著性推断。表中差值为测试指标减去100折均值。

{_markdown_table(devtest[['model','development_macro_f1_100fold_mean','development_macro_f1_20round_oof_mean','macro_f1','test_minus_development_macro_f1_100fold','development_balanced_accuracy_100fold_mean','balanced_accuracy','test_minus_development_balanced_accuracy_100fold','n_unique_genes']], digits=6)}

- **Top20（M2）**：测试Macro-F1={m2.macro_f1:.6f}，相对全特征M0差{m2.macro_f1-m0.macro_f1:+.6f}；是否足以维持性能，应结合该实际差距及区间解释，不能在没有预设容许界值时宣称等效。
- **ANOVA Top50（M1）与全特征M0**：测试Macro-F1差值M1−M0={m1.macro_f1-m0.macro_f1:+.6f}。M1作为主要报告模型由任务预先指定，不因测试表现改选。
- **ANOVA Top300（M3）**：开发100折Macro-F1为{m3.development_macro_f1_100fold_mean:.6f}；测试结果见表。与开发集表现比较时关注实际差值，不将开发集满分当作测试保证。
- **融合M4**：80个不重复基因；相对M1纠正{corrections['M4']['纠正M1错误']}个M1错误并新增{corrections['M4']['新增错误']}个错误；测试Macro-F1差值M4−M1={m4.macro_f1-m1.macro_f1:+.6f}。
- **硬投票M5**：实际独立基因数为{int(summary.loc[summary.model.eq('M5'),'n_unique_genes'].iloc[0])}，不是150个必然不同基因。相对M1纠正{corrections['M5']['纠正M1错误']}个错误、增加{corrections['M5']['新增错误']}个错误；M5比测试集最佳单模型{best_single.model}的Macro-F1差{m5_vs_best:+.6f}。这是描述性结果，不据此事后选择新模型。

## 各癌种表现与错误重合

{_markdown_table(perclass[['model','cancer_type','precision','recall','f1','support']], digits=6)}

M1混淆矩阵（真实类别为行，预测类别为列，类别顺序{', '.join(CLASS_ORDER)}）：

{_markdown_table(matrix.reset_index(), digits=0)}

六方案错误样本两两重合数见 `final_error_overlap.csv`，每个样本的六模型预测对照见 `final_test_predictions.csv`，错分样本ID及真实/预测类别见 `final_test_errors.csv`。本次共有{len(errors)}条“模型×错误样本”记录；其中至少被两个模型共同错分的样本数为{overlap_events}。M4/M5相对M1的具体纠错与新增错误见 `final_M4_M5_error_changes_vs_M1.csv`。错误数较少时仅作样本级描述，不进行小样本错误事件显著性检验。

各方案F1低于M1的癌种：{'；'.join(class_drops)}。逐类Precision、Recall、F1和support均已完整保存，避免只汇报总体分数。

## RQ1–RQ3及扩展实验结论

**RQ1：少量基因是否足以维持较高分类性能？** M2使用20个基因，M1使用50个，M3使用300个；其测试Macro-F1、Balanced Accuracy与全特征M0的数值差异见开发/测试对照表。结论按本次161例实际差值陈述；当前数据规模和历史探索暴露不支持将“接近”解释为正式等效或临床可替代。

**RQ2：不同筛选器的特征稳定性如何？** 不重跑已完成的30次分层子采样实验。K=50时方法内两两Jaccard均值为：高方差{stability50.loc['variance','jaccard_mean']:.6f}（SD {stability50.loc['variance','jaccard_std']:.6f}）、ANOVA {stability50.loc['anova','jaccard_mean']:.6f}（SD {stability50.loc['anova','jaccard_std']:.6f}）、LinearSVC L2系数 {stability50.loc['svc_l2','jaccard_mean']:.6f}（SD {stability50.loc['svc_l2','jaccard_std']:.6f}）。高方差集合在该开发集子采样分析中最稳定，系数筛选较不稳定；435个两两集合比较彼此相关，原分析只作描述性统计。161例测试只评价冻结模型预测，不验证特征选择稳定性。

| 方法 | K=50集合数 | 两两Jaccard均值±SD | Kuncheva均值 | 30次中始终入选基因数 |
|---|---:|---:|---:|---:|
{''.join(f"| {r.method} | {int(r.n_sets)} | {r.jaccard_mean:.6f} ± {r.jaccard_std:.6f} | {r.kuncheva_mean:.6f} | {int(r.n_always_selected)} |\n" for r in stability_table.itertuples(index=False))}

**RQ3：较高分类性能是否必然对应更稳定的特征集合？** 不能据此认为必然对应。开发集Top50对照中，ANOVA SVM与高方差SVM的性能相近（完整值见既有报告），但本次30次子采样下高方差Jaccard高于ANOVA；SVM系数法的Jaccard更低。性能与选择稳定性是不同属性，且Top-K高分本身不能说明生物学重要性。

**融合、投票与动态仲裁。** M4与M5的测试增益或损失均已按冻结方案完整报告。此前动态仲裁仅在开发集嵌套CV评估，学习规则在100折回退到M1；曾查看开发集分歧模式后制定的固定规则不进入本次六模型测试比较，其探索性回算分数不能当作独立验证结果。

## 可用于课程论文的结果分析

本研究在预先固定的640例开发集上完成重复交叉验证和特征稳定性分析，并按冻结流程使用全部开发样本重拟合六个方案，对同来源161例保留样本进行一次回顾性评价。主要模型M1（ANOVA Top50+LinearSVC）在保留集取得Accuracy {m1.accuracy:.4f}、Macro-F1 {m1.macro_f1:.4f}及Balanced Accuracy {m1.balanced_accuracy:.4f}。Accuracy的Wilson 95%区间为[{acc_ci[0]:.4f}, {acc_ci[1]:.4f}]；Macro-F1的分层患者bootstrap 95%区间为[{m1.macro_f1_stratified_bootstrap95_low:.4f}, {m1.macro_f1_stratified_bootstrap95_high:.4f}]。M0、M2、M3、M4和M5的测试结果及分癌种指标应结合表格完整解读，不依据测试分数更换主要模型。

开发集30次分层子采样显示，高方差Top50的平均Jaccard为{stability50.loc['variance','jaccard_mean']:.4f}，ANOVA Top50为{stability50.loc['anova','jaccard_mean']:.4f}，LinearSVC L2系数Top50为{stability50.loc['svc_l2','jaccard_mean']:.4f}。这说明在当前子采样扰动下，预测性能与基因集合稳定性没有简单的一一对应关系。测试集评价只检验冻结分类器的当前样本预测，不表示特征名单在新队列中稳定。

## 研究限制

1. 数据只含五类已确诊癌症肿瘤，没有健康对照，不能评价是否患癌、癌症早筛或患癌风险；没有纵向随访，不能评价进展、复发或治疗反应监测。
2. 161例来自同一数据来源，不是跨医院、跨平台外部验证。项目早期全801例探索性可视化涉及该测试集，需在论文中如实披露。
3. 特征为匿名`gene_*`列，不能将排序高或分类贡献大直接解释为致癌基因或临床标志物。
4. 测试集仅161例，类别级和bootstrap区间受样本量及样本构成限制；各模型的测试分数差异只作描述，不因一两个样本差别声称显著优势。
5. 既有重复CV折和轮次共享患者，不按100折进行独立样本推断；特征稳定性也仅来自开发集30次分层子采样。

后续应在未参与前期探索、来自独立医院或平台的队列中，在读取标签前冻结数据处理、模型、主要指标和分析计划，再进行外部验证。

## 文件索引

- 六模型配置及前置审计：`final_configuration.json`
- 最终评价审计：`final_evaluation_audit.json`
- 六模型性能及区间：`final_test_summary.csv`
- 开发集/测试集对照：`development_vs_test.csv`
- 每类别指标、逐样本预测、错误和混淆矩阵：对应CSV
- 实际特征清单与最终Pipeline：`final_selected_features.csv`、`models/`
- 七张330 DPI PNG和PDF：`figures/`
"""
    (out / "final_research_report.md").write_text(report, encoding="utf-8")
    best = summary.sort_values("macro_f1", ascending=False).iloc[0]
    conclusions = f"""# 课程论文结论（可直接改写）

本研究在五类肿瘤RNA-Seq表达数据上比较了全特征LinearSVC、ANOVA Top50、方差Top20、ANOVA Top300、ANOVA与方差补充特征融合，以及三模型等权硬投票。主要报告模型M1在读取保留集结果前已预先指定。按原640/161划分，M1在161例回顾性保留样本上的Accuracy为{m1.accuracy:.4f}，Macro-F1为{m1.macro_f1:.4f}，Balanced Accuracy为{m1.balanced_accuracy:.4f}；六个方案的完整测试结果及置信区间见主报告。

本次测试对照显示，20基因、50基因、300基因及全特征模型的表现差异应结合实测数值和类别级错误解释，不依据测试表现事后改选模型。开发集既有30次分层子采样结果中，高方差Top50的Jaccard均值（{stability50.loc['variance','jaccard_mean']:.4f}）高于ANOVA Top50（{stability50.loc['anova','jaccard_mean']:.4f}），LinearSVC L2系数Top50为{stability50.loc['svc_l2','jaccard_mean']:.4f}；因此，预测性能和特征选择稳定性应作为不同研究维度报告。

所有分类结果仅适用于BRCA、COAD、KIRC、LUAD和PRAD这五类已确诊肿瘤样本。由于不含健康对照、随访资料或跨来源外部队列，结果不能支持癌症早筛、患癌风险评估、疾病监测或临床应用结论。161例来自同一数据源，且曾受到项目早期全样本探索性可视化影响；应将本次结果称为回顾性保留集评价，而不是完全独立的外部验证。匿名基因特征也不足以识别致癌基因或临床标志物。
"""
    (out / "final_paper_conclusions.md").write_text(conclusions, encoding="utf-8")


def prediction_pattern_error_count(tables: dict) -> pd.Series:
    pat = tables["error_patterns"]
    return pat.loc[pat.error_pattern.ne("无模型错误"), "n_samples"]


def run() -> Path:
    cfg = ExperimentConfig(cv_mode="repeated")
    out = PROJECT_DIR / "results" / "final_holdout_evaluation"
    if out.exists():
        raise FileExistsError(f"最终评价目录已存在，防止重复打开/评分保留集：{out}")
    audit = preflight()
    out.mkdir(parents=True, exist_ok=False)
    (out / "models").mkdir()
    (out / "checkpoints").mkdir()
    atomic_json(out / "final_evaluation_audit.json", {
        "status": "preflight_passed", "preflight": audit,
        "test_expression_rows_parsed": 0, "test_labels_parsed": False,
        "model_fit_started": False, "predictions_written_before_test_labels": False,
    })
    configuration = freeze_configuration(out, audit, cfg)
    dev = load_existing_development_data(cfg, out, strict_rows_only=True)
    manifest = read_json(cfg.split_manifest_path)
    feature_names = list(dev.X.columns)
    if (list(dev.X.index.astype(str)) != manifest["development_ids"] or
            tuple(dev.reserved_test_ids) != tuple(manifest["reserved_test_ids"]) or
            len(feature_names) != 20531 or len(set(feature_names)) != 20531):
        raise RuntimeError("开发样本顺序、保留样本ID或表达列顺序与固定清单不一致")
    record = read_json(out / "development_data_record.json")
    if record["development_fingerprint_sha256"] != configuration["preflight"]["development_fingerprint"]:
        raise RuntimeError("本次640例开发矩阵与既有冻结开发数据指纹不一致")
    if not np.isfinite(dev.X.to_numpy(dtype=np.float64)).all() or dev.y.isna().any():
        raise ValueError("开发集存在非有限表达值或缺失标签")
    audit_state = {
        "status": "development_verified_configuration_frozen",
        "preflight": audit, "development_samples": 640, "test_samples": 161,
        "development_sample_order_matches_manifest": True,
        "development_feature_order": "gene_0 ... gene_20530",
        "development_fingerprint_matches_history": True,
        "test_expression_rows_parsed": 0, "test_labels_parsed": False,
        "final_configuration_sha256": sha256(out / "final_configuration.json"),
        "model_fit_started": False,
    }
    atomic_json(out / "final_evaluation_audit.json", audit_state)
    dev_metrics = collect_development_metrics(audit["sources"])

    models = make_models(cfg)
    selected_records, unique_gene_counts, fit_audits = [], {}, []
    warnings_by_model, model_paths, run_times = {}, {}, {}
    for model_id in MODEL_ORDER:
        model = models[model_id]
        warnings_by_model[model_id] = []
        start = time.perf_counter()
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
            warnings.simplefilter("always")
            model.fit(dev.X, dev.y.to_numpy(dtype=str))
        fit_seconds = time.perf_counter() - start
        warnings_by_model[model_id] = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
        audits = audit_fitted_model(model_id, model, 640)
        fit_audits.extend(audits)
        records, unique = extract_feature_records(model_id, model, feature_names)
        selected_records.extend(records)
        unique_gene_counts[model_id] = unique
        model_path = out / "models" / f"{model_id}.joblib"
        joblib.dump(model, model_path, compress=3)
        model_paths[model_id] = model_path
        run_times[model_id] = {"fit_seconds": fit_seconds, "predict_seconds": 0.0}
    selected_table = pd.DataFrame(selected_records)
    write_csv(selected_table, out / "final_selected_features.csv")
    fit_audit_table = pd.DataFrame(fit_audits)
    write_csv(fit_audit_table, out / "final_model_fit_audit.csv")

    # 此处首次解析161例表达值；从未解析测试标签。所有模型和参数已冻结并完整拟合。
    test_ids = list(manifest["reserved_test_ids"])
    x_test = load_test_features_only(cfg, manifest["development_ids"], test_ids, feature_names)
    predictions = pd.DataFrame({"sample_id": test_ids})
    prediction_seconds = {}
    for model_id in MODEL_ORDER[:-1]:
        start = time.perf_counter()
        with threadpool_limits(limits=1):
            predictions[f"pred_{model_id}"] = models[model_id].predict(x_test).astype(str)
        prediction_seconds[model_id] = time.perf_counter() - start
    start = time.perf_counter()
    with threadpool_limits(limits=1):
        members = models["M5"].predict_members(x_test).astype(str)
        voted, vote_info = vote_labels(members)
    prediction_seconds["M5"] = time.perf_counter() - start
    for j, member in enumerate("ABC"):
        predictions[f"M5_member_{member}"] = members[:, j]
    predictions["pred_M5"] = voted.astype(str)
    for key, values in vote_info.items():
        if key in ("has_majority", "all_three_different", "tie_rule_applied", "unanimous", "winning_vote_count"):
            predictions[f"M5_{key}"] = values
    for model_id in MODEL_ORDER:
        run_times[model_id]["predict_seconds"] = prediction_seconds[model_id]
    # 预测快照不包含真实标签，确保预测和模型选择先于测试标签解析。
    write_csv(predictions, out / "checkpoints/test_predictions_before_labels.csv")
    prediction_sha = sha256(out / "checkpoints/test_predictions_before_labels.csv")
    audit_state.update({
        "status": "all_predictions_frozen_before_test_labels",
        "test_expression_rows_parsed": len(x_test), "test_labels_parsed": False,
        "predictions_written_before_test_labels": True,
        "test_prediction_rows_per_model": {m: int(len(predictions)) for m in MODEL_ORDER},
        "test_prediction_snapshot_sha256": prediction_sha,
        "all_six_model_fits_completed_before_test_labels": True,
        "model_fit_audits": fit_audits,
        "model_artifacts_sha256": {m: sha256(p) for m, p in model_paths.items()},
        "unique_gene_counts": unique_gene_counts,
        "convergence_warnings": warnings_by_model,
        "model_times_seconds": run_times,
    })
    atomic_json(out / "final_evaluation_audit.json", audit_state)

    # 测试标签只在六种预测已保存后读取；不再改变模型、参数或规则。
    y_test = load_test_labels_after_prediction(cfg, manifest["development_ids"], test_ids)
    if list(y_test.index.astype(str)) != test_ids:
        raise RuntimeError("测试标签按样本ID重排后仍未匹配固定保留顺序")
    predictions.insert(1, "y_true", y_test.to_numpy(dtype=str))
    for model_id in MODEL_ORDER:
        if not predictions[f"pred_{model_id}"].isin(CLASS_ORDER).all():
            raise ValueError(f"{model_id}产生未知类别预测")
    tables = calculate_outputs(out, configuration, dev_metrics, y_test, predictions,
                               selected_table, unique_gene_counts, fit_audits,
                               warnings_by_model, model_paths, run_times)
    stability_path = Path(audit["sources"]["latest_full_feature_ablation.json"]) / "stability/stability_summary.csv"
    stability = pd.read_csv(stability_path)
    if not {"variance", "anova", "svc_l2"}.issubset(set(stability.method)) or not (stability.k == 50).any():
        raise RuntimeError("既有30次分层子采样稳定性结果缺少K=50的三种方法")
    write_reports(out, tables, stability, audit, configuration)
    plot_all(out, tables)

    audit_state.update({
        "status": "complete", "test_labels_parsed": True,
        "test_labels_parsed_after_predictions": True,
        "test_samples_scored": 161, "test_predictions_written_before_test_labels": True,
        "test_set_fit_samples": 0, "test_set_selector_fit_samples": 0,
        "test_set_scaler_fit_samples": 0, "test_set_model_selection_or_tuning": False,
        "final_model_selection_changed_after_test": False,
        "training_sample_ids": list(dev.X.index.astype(str)),
        "test_sample_ids": test_ids,
        "prediction_snapshot_sha256_before_labels": prediction_sha,
        "final_outputs": {str(p.relative_to(out)): sha256(p) for p in out.rglob("*") if p.is_file() and p.name not in ("final_evaluation_audit.json",)},
    })
    atomic_json(out / "final_evaluation_audit.json", audit_state)
    atomic_json(out / "status.json", {"status": "complete", "completed": datetime.now().isoformat(),
                                       "test_evaluation_performed": True, "models": list(MODEL_ORDER),
                                       "no_post_test_model_selection": True})
    atomic_json(PROJECT_DIR / "results/latest_final_holdout_evaluation.json",
                {"run_directory": str(out.relative_to(PROJECT_DIR / "results")), "status": "complete"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true", help="只审查既有划分/实验日志，不读取保留集表达值或标签")
    args = parser.parse_args()
    if args.preflight_only:
        result = preflight()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(run())


if __name__ == "__main__":
    main()


