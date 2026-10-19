# -*- coding: utf-8 -*-
"""从已审计的最终M1工件打包部署模型；不读取原始表达或测试集。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "results" / "final_holdout_evaluation"
DEST = ROOT / "deployment"
MODEL_NAME = "ANOVA Top50 + LinearSVC"
MODEL_VERSION = "M1-anova50-linearsvc-1.0.0"
EXPECTED_SOURCE_SHA256 = "323c5e9c28faf5426467e17c5429e593235a4c811519e9e1efe04c4910aef7d4"
CLASS_DESCRIPTIONS = {
    "BRCA": "乳腺浸润性癌", "COAD": "结肠腺癌", "KIRC": "肾透明细胞癌",
    "LUAD": "肺腺癌", "PRAD": "前列腺腺癌",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    audit_path = EVALUATION_DIR / "final_evaluation_audit.json"
    config_path = EVALUATION_DIR / "final_configuration.json"
    source_path = EVALUATION_DIR / "models" / "M1.joblib"
    if not all(path.is_file() for path in (audit_path, config_path, source_path)):
        raise FileNotFoundError("缺少已完成的最终评价审计、配置或M1 Pipeline；拒绝另行训练")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if audit.get("status") != "complete" or config.get("primary_model") != "M1":
        raise RuntimeError("最终评价未完成或主要模型身份与预先冻结的M1不符")
    source_digest = sha256(source_path)
    if source_digest != EXPECTED_SOURCE_SHA256 or audit["model_artifacts_sha256"].get("M1") != source_digest:
        raise RuntimeError("原M1工件哈希与最终评价审计不一致，拒绝加载或复制")
    fit_records = [row for row in audit["model_fit_audits"] if row["model"] == "M1"]
    if (len(fit_records) != 1 or fit_records[0]["fit_samples"] != 640 or
            fit_records[0]["reserved_test_fit_samples"] != 0 or
            fit_records[0]["scaler_fit_features"] != 50):
        raise RuntimeError("M1拟合审计未确认只用640个开发样本且筛选50个基因")

    # 唯一反序列化来源是项目自身最终评价产生并经审计哈希固定的本地工件。
    pipeline = joblib.load(source_path)
    if (not isinstance(pipeline, Pipeline) or list(pipeline.named_steps) != ["select", "scale", "model"] or
            not isinstance(pipeline.named_steps["select"], SelectKBest) or
            pipeline.named_steps["select"].score_func is not f_classif or
            not isinstance(pipeline.named_steps["scale"], StandardScaler) or
            not isinstance(pipeline.named_steps["model"], LinearSVC)):
        raise RuntimeError("源工件不含完整冻结的ANOVA/StandardScaler/LinearSVC Pipeline")
    selector, scaler, classifier = (pipeline.named_steps[name] for name in ("select", "scale", "model"))
    names = tuple(str(name) for name in selector.feature_names_in_)
    selected = tuple(names[i] for i in np.flatnonzero(selector.get_support()))
    if (len(names) != 20531 or names != tuple(f"gene_{i}" for i in range(20531)) or
            selector.k != 50 or len(selected) != 50 or classifier.C != 1.0 or
            classifier.dual != "auto" or scaler.n_samples_seen_ != 640 or
            not np.isfinite(selector.scores_[selector.get_support()]).all()):
        raise RuntimeError("源模型拟合维度、选择结果或冻结参数不符")
    selected_manifest = pd.read_csv(EVALUATION_DIR / "final_selected_features.csv")
    recorded_genes = tuple(selected_manifest.loc[selected_manifest.model.eq("M1"), "gene_id"].astype(str))
    if recorded_genes != selected:
        raise RuntimeError("Pipeline内部选中特征与最终评价保存的M1特征名单不一致")

    models_dir = DEST / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    packaged_model = models_dir / "M1_anova_top50.joblib"
    shutil.copy2(source_path, packaged_model)
    artifact_digest = sha256(packaged_model)
    class_order = [str(label) for label in classifier.classes_]
    environment = {name: importlib.metadata.version(distribution) for name, distribution in (
        ("scikit-learn", "scikit-learn"), ("numpy", "numpy"), ("pandas", "pandas"),
        ("joblib", "joblib"))}
    environment["python"] = platform.python_version()
    metadata = {
        "metadata_schema_version": 1,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "model_artifact_file": packaged_model.name,
        "model_artifact_sha256": artifact_digest,
        "packaged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_configuration": {
            "pipeline_steps": ["SelectKBest(f_classif, k=50)", "StandardScaler()",
                               "LinearSVC(C=1.0, dual='auto')"],
            "selector": {"class": "sklearn.feature_selection.SelectKBest", "score_function": "f_classif", "k": 50},
            "standard_scaler": {"with_mean": scaler.with_mean, "with_std": scaler.with_std},
            "linear_svc": {"C": classifier.C, "dual": classifier.dual, "penalty": classifier.penalty,
                           "loss": classifier.loss, "class_weight": classifier.class_weight,
                           "max_iter": classifier.max_iter, "tol": classifier.tol,
                           "random_state": classifier.random_state, "multi_class": classifier.multi_class},
        },
        "training_provenance": {
            "dataset": "UCI Machine Learning Repository Dataset 401: Gene Expression Cancer RNA-Seq",
            "training_data_source": "同一数据集固定开发集；640个样本；不包含161个保留测试样本",
            "source_final_pipeline": "results/final_holdout_evaluation/models/M1.joblib",
            "source_final_pipeline_sha256": source_digest,
            "split_manifest_sha256": config["split"]["manifest_sha256"],
            "development_data_fingerprint_sha256": audit["preflight"]["development_fingerprint"],
            "fit_audit": {key: fit_records[0][key] for key in (
                "fit_samples", "selector_fit_samples", "scaler_fit_samples", "scaler_fit_features",
                "classifier_fit_features", "selector_fit_features", "reserved_test_fit_samples",
                "development_ids_only", "train_test_id_overlap")},
        },
        "training_sample_count": 640,
        "raw_feature_count": len(names),
        "selected_feature_count": len(selected),
        "raw_feature_names": list(names),
        "selected_gene_names": list(selected),
        "classifier_class_order": class_order,
        "class_descriptions": CLASS_DESCRIPTIONS,
        "random_seed": classifier.random_state,
        "environment": environment,
        "applicability": [
            "仅用于与UCI Dataset 401列名、基因定义和表达值处理尺度兼容的研究数据。",
            "仅将样本分到BRCA、COAD、KIRC、LUAD、PRAD五种既有肿瘤类别之一。",
            "预测类别不表示概率、患癌风险、临床诊断、癌症早筛或病情监测结果。",
            "需由专业人员核验输入来源、表达量单位、归一化处理和基因定义兼容性。",
        ],
        "data_citation": "Fiorini, S. (2016). gene expression cancer RNA-Seq. UCI Machine Learning Repository. https://doi.org/10.24432/C5R88H.",
        "data_license": "UCI页面标示CC BY 4.0；再分发须保留适当署名、引用并遵守上游许可条款。",
    }
    metadata_path = models_dir / "M1_anova_top50.metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                             encoding="utf-8")
    selected_rank = {gene: i + 1 for i, gene in enumerate(selected)}
    pd.DataFrame({
        "raw_feature_index": np.arange(len(names), dtype=int),
        "gene_id": names,
        "selected_by_M1": [gene in selected_rank for gene in names],
        "selected_gene_order": [selected_rank.get(gene, "") for gene in names],
    }).to_csv(models_dir / "M1_anova_top50_gene_manifest.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({"model": str(packaged_model.relative_to(DEST)),
                      "metadata": str(metadata_path.relative_to(DEST)),
                      "model_sha256": artifact_digest, "raw_features": len(names),
                      "selected_features": len(selected), "classes": class_order,
                      "scikit_learn": environment["scikit-learn"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
