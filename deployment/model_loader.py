# -*- coding: utf-8 -*-
"""只加载哈希固定、来源可信且结构符合冻结方案的M1 Pipeline。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

MODEL_VERSION = "M1-anova50-linearsvc-1.0.0"
# 仅接受本次已经审计的项目内模型工件；替换正式模型时须经审核同步更新两个固定摘要。
TRUSTED_MODEL_SHA256 = "323c5e9c28faf5426467e17c5429e593235a4c811519e9e1efe04c4910aef7d4"
TRUSTED_METADATA_SHA256 = "d52a3514848864a910bc2d8369b45292c2cb2cca2f515183112bc60c62ccc31b"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "M1_anova_top50.joblib"


class ModelArtifactError(RuntimeError):
    """模型工件不存在、损坏、版本不符或不属于本项目可信模型。"""


@dataclass(frozen=True)
class LoadedModel:
    pipeline: Pipeline
    metadata: dict[str, Any]
    model_path: Path
    feature_names: tuple[str, ...]
    selected_gene_names: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata_path_for(model_path: Path) -> Path:
    return model_path.with_name(f"{model_path.stem}.metadata.json")


def load_deployment_model(model_path: str | Path | None = None) -> LoadedModel:
    """验证可信摘要、运行版本和拟合Pipeline结构后加载模型。

    joblib/pickle可执行反序列化行为。模型和元数据都必须与本项目固定SHA-256完全匹配；
    不接受仅由调用者自报摘要的新工件。
    """
    path = Path(model_path).expanduser() if model_path is not None else DEFAULT_MODEL_PATH
    if not path.exists() or not path.is_file():
        raise ModelArtifactError(f"找不到模型文件：{path}")
    metadata_file = metadata_path_for(path)
    if not metadata_file.exists() or not metadata_file.is_file():
        raise ModelArtifactError(f"找不到模型元数据文件：{metadata_file}")
    if TRUSTED_MODEL_SHA256 == "SET_AFTER_PACKAGING" or TRUSTED_METADATA_SHA256 == "SET_AFTER_PACKAGING":
        raise ModelArtifactError("部署模型尚未完成可信摘要固定，拒绝加载")

    try:
        model_digest = _sha256(path)
        metadata_digest = _sha256(metadata_file)
    except OSError as exc:
        raise ModelArtifactError(f"无法读取模型工件：{exc}") from exc
    if model_digest != TRUSTED_MODEL_SHA256:
        raise ModelArtifactError("模型SHA-256与代码中的可信工件摘要不一致；文件可能损坏或已被替换")
    if metadata_digest != TRUSTED_METADATA_SHA256:
        raise ModelArtifactError("模型元数据SHA-256与代码中的可信摘要不一致；拒绝继续")

    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelArtifactError(f"模型元数据无法解析：{exc}") from exc
    if metadata.get("model_version") != MODEL_VERSION:
        raise ModelArtifactError(
            f"模型版本不匹配：要求{MODEL_VERSION}，实际{metadata.get('model_version')!r}")
    if metadata.get("model_artifact_sha256") != model_digest:
        raise ModelArtifactError("模型元数据中的工件摘要与模型文件不一致")

    recorded_versions = metadata.get("environment", {})
    runtime_versions = {"python": platform.python_version(),
                        "scikit-learn": sklearn.__version__, "numpy": np.__version__,
                        "joblib": joblib.__version__}
    mismatches = [f"{name}:要求{recorded_versions.get(name)}，当前{version}"
                  for name, version in runtime_versions.items()
                  if recorded_versions.get(name) != version]
    if mismatches:
        raise ModelArtifactError("模型运行环境版本不匹配；请使用部署requirements.txt：" + "；".join(mismatches))

    try:
        pipeline = joblib.load(path)
    except Exception as exc:
        raise ModelArtifactError(f"模型文件损坏或无法反序列化：{type(exc).__name__}: {exc}") from exc
    if not isinstance(pipeline, Pipeline) or list(pipeline.named_steps) != ["select", "scale", "model"]:
        raise ModelArtifactError("模型不是预期的已拟合三步scikit-learn Pipeline")
    selector, scaler, classifier = (pipeline.named_steps[name] for name in ("select", "scale", "model"))
    if not isinstance(selector, SelectKBest) or selector.score_func is not f_classif or selector.k != 50:
        raise ModelArtifactError("Pipeline特征选择器与冻结的ANOVA Top50配置不符")
    if not isinstance(scaler, StandardScaler) or not hasattr(scaler, "mean_"):
        raise ModelArtifactError("Pipeline内StandardScaler不存在或未拟合")
    if not isinstance(classifier, LinearSVC) or not hasattr(classifier, "coef_"):
        raise ModelArtifactError("Pipeline内LinearSVC不存在或未拟合")
    if classifier.C != 1.0 or classifier.dual != "auto":
        raise ModelArtifactError("LinearSVC参数不符合冻结配置")

    names = tuple(str(name) for name in getattr(selector, "feature_names_in_", ()))
    if len(names) != 20531 or len(set(names)) != 20531 or selector.n_features_in_ != 20531:
        raise ModelArtifactError("模型没有完整、唯一的20531列训练特征名")
    if tuple(str(name) for name in getattr(pipeline, "feature_names_in_", ())) != names:
        raise ModelArtifactError("Pipeline原始特征名/顺序与ANOVA选择器记录不一致")
    selected = tuple(names[index] for index in np.flatnonzero(selector.get_support()))
    if len(selected) != 50 or selected != tuple(metadata.get("selected_gene_names", ())):
        raise ModelArtifactError("Pipeline实际选中的50个基因与元数据不一致")
    if names != tuple(metadata.get("raw_feature_names", ())):
        raise ModelArtifactError("训练特征名称或原始顺序与元数据不一致")
    class_names = tuple(str(name) for name in classifier.classes_)
    if class_names != tuple(metadata.get("classifier_class_order", ())):
        raise ModelArtifactError("分类器类别编码/顺序与元数据不一致")
    if scaler.n_features_in_ != 50 or classifier.n_features_in_ != 50 or scaler.n_samples_seen_ != 640:
        raise ModelArtifactError("Scaler或分类器拟合维度/样本数与开发集审计不一致")
    if not np.isfinite(selector.scores_[selector.get_support()]).all():
        raise ModelArtifactError("选中特征包含非有限ANOVA F-score")

    return LoadedModel(pipeline, metadata, path.resolve(), names, selected)
