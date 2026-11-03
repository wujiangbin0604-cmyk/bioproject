# -*- coding: utf-8 -*-
"""实验室冻结模型注册：先验摘要、精确环境和结构验证；绝不训练模型。"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import platform
import shutil
import time

import joblib
import numpy as np
import sklearn
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from deployment.input_validator import validate_single_sample
from deployment.model_loader import ModelArtifactError, load_deployment_model

ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / "deployment" / "lab_models"
SOURCE = ROOT / "results" / "final_holdout_evaluation"
FEATURES = tuple(f"gene_{i}" for i in range(20531))
CLASSES = ("BRCA", "COAD", "KIRC", "LUAD", "PRAD")
ENVIRONMENT = {"python": "3.14.0", "numpy": "2.4.2", "scikit-learn": "1.8.0", "joblib": "1.5.3"}
SPLIT_SHA = "602b05c207c8470f9d313d15781907b3bf10909a4017bc97a757bbcfc692b75f"
CONFIG_SHA = "603d146017414a2c60396f4288f2400b442dbc4b390085ae07855678efce6844"
AUDIT_SHA = "36ecf0db57cd2f2439f795770cd60daae4a1e3a60e18d569dd8c8f3ba18997cd"
MODEL_SHA = {
    "M0": "dceb28b2262ababba2f98ed9025190e1daa23744a92cca89bb3cfa00ac187824",
    "M1": "323c5e9c28faf5426467e17c5429e593235a4c811519e9e1efe04c4910aef7d4",
    "M2": "831578ea6a1952cf20ff8c9853396c17481a2111337f95eb320070a8365d653d",
    "M3": "6e78fcb94401ff4225e1988444f6ce20258d492a74c3863276e2aa6554df8592",
    "M4": "89d1758a9ffed2b9eb6f17158bbe6b6cc5f889e002f656977031a11f7c1b40b7",
    "M5": "3b0eae05fc90a2f468c4aa987717527fa0b69735a28373e991cacad1a407b257",
}
# 已逐行审阅当前自定义类型。variance_topk 与历史快照仅差一行排序说明注释。
CUSTOM_SOURCE_SHA = {
    "variance_topk.py": "b7063f3aa45b6ee7ef7046ee587305d5117f79a677f944b2a0215cccf4608a37",
    "fusion_selection.py": "ca25558d28a69fb39899fd827569cc880beddf956ce62383c04e3db59156f2cf",
    "hard_voting.py": "e946b3d6052150f7403112102daa9e71dac587ff49395b09eaefdfa9a5f6a9b9",
}
NAMES = {
    "M0": "全特征 + Linear SVM", "M1": "ANOVA Top50 + Linear SVM",
    "M2": "高方差 Top20 + Linear SVM", "M3": "ANOVA Top300 + Linear SVM",
    "M4": "ANOVA50 + 高方差补充30 + Linear SVM", "M5": "三模型等权硬投票",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_environment() -> None:
    actual = {"python": platform.python_version(), "numpy": np.__version__,
              "scikit-learn": sklearn.__version__, "joblib": joblib.__version__}
    if actual != ENVIRONMENT:
        raise ModelArtifactError("冻结模型环境不匹配：要求 " + json.dumps(ENVIRONMENT, ensure_ascii=False)
                                 + "；当前 " + json.dumps(actual, ensure_ascii=False))


def check_digest(path: Path, expected: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise ModelArtifactError(f"可信工件缺失或SHA-256不匹配：{path.name}")


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if callable(value):
        return f"{value.__module__}.{value.__name__}"
    if isinstance(value, np.generic):
        return value.item()
    return value


def describe_model(model_id, model):
    """核对已拟合组件、配置、维度和基因并集；不需要患者或测试集。"""
    from variance_topk import VarianceTopK
    from fusion_selection import FusionSelector
    from hard_voting import ThreeModelHardVotingClassifier

    if model_id == "M5":
        if type(model) is not ThreeModelHardVotingClassifier or len(model.estimators_) != 3:
            raise ModelArtifactError("M5不是冻结的三模型投票器")
        if model.n_features_in_ != 20531 or tuple(model.classes_) != CLASSES:
            raise ModelArtifactError("M5输入维度或类别顺序异常")
        members = list(zip("ABC", model.estimators_))
    else:
        members = [(model_id, model)]
    descriptions, union = [], set()
    for member_id, pipe in members:
        expected_n = 20531 if model_id == "M0" else 20 if model_id == "M2" else 300 if model_id == "M3" else 80 if model_id == "M4" else 50
        if type(pipe) is not Pipeline or list(pipe.named_steps) != (["scale", "model"] if model_id == "M0" else ["select", "scale", "model"]):
            raise ModelArtifactError("Pipeline步骤与冻结配置不符")
        if pipe.n_features_in_ != 20531:
            raise ModelArtifactError("Pipeline原始输入维度异常")
        saved_names = getattr(pipe, "feature_names_in_", None)
        if saved_names is not None and tuple(saved_names) != FEATURES:
            raise ModelArtifactError("Pipeline原始列名顺序异常")
        selector = pipe.named_steps.get("select")
        is_variance = model_id == "M2" or (model_id == "M5" and member_id == "B")
        if selector is None:
            indices = np.arange(20531)
        else:
            if is_variance:
                if type(selector) is not VarianceTopK or selector.k != expected_n:
                    raise ModelArtifactError("高方差筛选配置不匹配")
                expected = np.argsort(-selector.variances_, kind="stable")[:expected_n]
                if set(expected) != set(selector.get_support(indices=True)):
                    raise ModelArtifactError("高方差支持集与保存方差不符")
            elif model_id == "M4":
                if type(selector) is not FusionSelector or (selector.rule, selector.k, selector.increment) != ("add_variance", 50, 30):
                    raise ModelArtifactError("M4融合规则不符")
                from fusion_selection import choose_features
                expected = choose_features(selector.anova_rank_, selector.variance_rank_, "add_variance", 50, 30)
                if set(expected) != set(selector.get_support(indices=True)):
                    raise ModelArtifactError("M4支持集与冻结排名规则不符")
            elif type(selector) is not SelectKBest or selector.score_func is not f_classif or selector.k != expected_n:
                raise ModelArtifactError("ANOVA配置不匹配")
            indices = selector.get_support(indices=True)
            if selector.n_features_in_ != 20531:
                raise ModelArtifactError("筛选器输入维度异常")
            if type(selector) is SelectKBest and not np.isfinite(selector.scores_[indices]).all():
                raise ModelArtifactError("入选ANOVA分数非有限")
        genes = [FEATURES[int(i)] for i in indices]
        if len(set(genes)) != expected_n:
            raise ModelArtifactError("实际基因数量不匹配")
        scaler, classifier = pipe.named_steps["scale"], pipe.named_steps["model"]
        if type(scaler) is not StandardScaler or not scaler.with_mean or not scaler.with_std or scaler.n_samples_seen_ != 640 or scaler.n_features_in_ != expected_n:
            raise ModelArtifactError("标准化器拟合样本数/配置不符")
        is_lr = model_id == "M5" and member_id == "C"
        if type(classifier) is not (LogisticRegression if is_lr else LinearSVC):
            raise ModelArtifactError("分类器类型不符")
        params = classifier.get_params(deep=False)
        required = {"C": 1.0, "max_iter": 50000, "tol": 1e-4, "random_state": 42, "class_weight": None}
        required.update({"solver": "lbfgs"} if is_lr else {"dual": "auto", "loss": "squared_hinge", "penalty": "l2"})
        if any(params.get(k) != v for k, v in required.items()) or classifier.n_features_in_ != expected_n or tuple(classifier.classes_) != CLASSES:
            raise ModelArtifactError("分类器参数/类别顺序/维度不符")
        if not all(np.isfinite(a).all() for a in (scaler.mean_, scaler.var_, classifier.coef_, classifier.intercept_)):
            raise ModelArtifactError("已拟合参数存在非有限值")
        union.update(genes)
        descriptions.append({"member": member_id, "genes": genes, "classifier": _canonical(params)})
    return {"schema_version": 1, "model_id": model_id, "model_version": f"{model_id}-frozen-lab-1.0.0",
            "name": NAMES[model_id], "artifact_sha256": MODEL_SHA[model_id], "environment": ENVIRONMENT,
            "raw_feature_count": 20531, "raw_feature_order": "gene_0..gene_20530", "classes": list(CLASSES),
            "training_samples": 640, "reserved_test_fit_samples": 0, "unique_gene_count": len(union),
            "members": descriptions, "split_manifest_sha256": SPLIT_SHA, "source_configuration_sha256": CONFIG_SHA,
            "source_audit_sha256": AUDIT_SHA, "reviewed_custom_sources": CUSTOM_SOURCE_SHA,
            "tie_rule": "all_three_different_use_A" if model_id == "M5" else None}


@lru_cache(maxsize=6)
def load_registered(model_id: str):
    if model_id not in NAMES:
        raise ModelArtifactError("未知模型ID")
    if model_id == "M1":
        original = load_deployment_model()  # 原有M1双摘要和精确版本校验完整保留。
        return original.pipeline, {"model_id": "M1", "name": NAMES["M1"], "model_version": original.metadata["model_version"], "unique_gene_count": 50}
    check_environment()
    for filename, digest in CUSTOM_SOURCE_SHA.items():
        check_digest(ROOT / filename, digest)
    path = EXPORT_DIR / f"{model_id}.joblib"
    check_digest(path, MODEL_SHA[model_id])  # 反序列化之前验证代码中固定的来源摘要。
    metadata_file = EXPORT_DIR / f"{model_id}.metadata.json"
    if not metadata_file.is_file():
        raise ModelArtifactError("尚未安全导出/注册：缺少模型元数据")
    supplied = json.loads(metadata_file.read_text(encoding="utf-8"))
    model = joblib.load(path)
    expected = describe_model(model_id, model)
    # 元数据不作为信任根：逐字段对照可信工件重新构造的确定性元数据。
    if supplied != expected:
        raise ModelArtifactError("注册元数据与可信工件的完整校验结果不一致")
    return model, expected


def model_statuses():
    items = []
    for key, name in NAMES.items():
        item = {"model_id": key, "name": name, "available": False, "reason": None,
                "model_version": None, "unique_gene_count": None}
        try:
            _, metadata = load_registered(key)
            item.update(available=True, model_version=metadata["model_version"], unique_gene_count=metadata["unique_gene_count"])
        except Exception as exc:
            item["reason"] = str(exc).replace(str(ROOT), "项目目录")[:1500]
        items.append(item)
    return items


def predict_registered(frame, ids):
    validated = validate_single_sample(frame, FEATURES)
    results = []
    for key in ids:
        start = time.perf_counter()
        try:
            model, metadata = load_registered(key)
            pred = str(model.predict(validated.features)[0])
            if pred not in CLASSES:
                raise ModelArtifactError("模型输出未知类别")
            results.append({"model_id": key, "status": "success", "predicted_class": pred,
                            "inference_ms": (time.perf_counter() - start) * 1000,
                            "unique_gene_count": metadata["unique_gene_count"], "model_version": metadata["model_version"], "error": None})
        except Exception as exc:
            results.append({"model_id": key, "status": "unavailable", "predicted_class": None,
                            "inference_ms": None, "unique_gene_count": None, "model_version": None,
                            "error": str(exc).replace(str(ROOT), "项目目录")[:1500]})
    return {"source": "live_frozen_model_inference", "sample_id": validated.sample_id,
            "probability_output": False, "input_feature_count": 20531, "results": results,
            "timing_scope": "校验后的单模型加载/缓存读取及predict墙钟耗时；非并行基准"}


def export_models():
    """离线命令，服务端不暴露导出/信任新工件接口；不读取任何患者数据。"""
    check_environment()
    check_digest(SOURCE / "final_configuration.json", CONFIG_SHA)
    check_digest(SOURCE / "final_evaluation_audit.json", AUDIT_SHA)
    check_digest(ROOT / "data" / "split_manifest.json", SPLIT_SHA)
    for filename, digest in CUSTOM_SOURCE_SHA.items():
        check_digest(ROOT / filename, digest)
    audit = json.loads((SOURCE / "final_evaluation_audit.json").read_text(encoding="utf-8"))
    if audit["status"] != "complete" or any(r["reserved_test_fit_samples"] != 0 or r["fit_samples"] != 640 for r in audit["model_fit_audits"]):
        raise ModelArtifactError("历史拟合范围审计未通过")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    for key in NAMES:
        if key == "M1":
            load_deployment_model()
            continue
        source = SOURCE / "models" / f"{key}.joblib"
        check_digest(source, MODEL_SHA[key])
        metadata = describe_model(key, joblib.load(source))
        target = EXPORT_DIR / source.name
        if target.exists():
            check_digest(target, MODEL_SHA[key])
        else:
            shutil.copyfile(source, target)
        text = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        meta = EXPORT_DIR / f"{key}.metadata.json"
        if meta.exists() and json.loads(meta.read_text(encoding="utf-8")) != metadata:
            raise ModelArtifactError("已有注册元数据冲突，拒绝覆盖")
        meta.write_text(text, encoding="utf-8")
    load_registered.cache_clear()
    return model_statuses()


if __name__ == "__main__":
    print(json.dumps(export_models(), ensure_ascii=False, indent=2))
