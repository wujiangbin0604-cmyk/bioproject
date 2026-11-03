"""只读的640例开发数据包；验证固定指纹后以内存映射读取，未导出保留值。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from backend.app.lab_config import DEVELOPMENT_SHA


def bundle_directory() -> Path | None:
    value = os.getenv("GENESCOPE_LAB_DEVELOPMENT_DIR")
    return Path(value).resolve() if value else None


def bundle_metadata(directory: Path) -> dict:
    """轻量状态检查；完整矩阵摘要和指纹在工作进程内校验。"""
    if directory.is_symlink():
        raise ValueError("开发数据目录不允许使用符号链接")
    path = directory / "development_metadata.json"
    matrix = directory / "development.npy"
    if path.is_symlink() or matrix.is_symlink() or not path.is_file() or not matrix.is_file():
        raise ValueError("640例开发数据包缺失或包含符号链接")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("schema_version") != 1 or record.get("shape") != [640, 20531]:
        raise ValueError("开发包不是640样本、20531基因")
    if record.get("development_fingerprint_sha256") != DEVELOPMENT_SHA or record.get("reserved_expression_included") is not False:
        raise ValueError("开发包指纹或保留集隔离标记不符")
    if record.get("gene_ids") != [f"gene_{i}" for i in range(20531)]:
        raise ValueError("开发包的原始基因列名或顺序不符")
    ids, labels = record.get("sample_ids", []), record.get("labels", [])
    if len(ids) != 640 or len(set(ids)) != 640 or len(labels) != 640:
        raise ValueError("开发包样本或标签记录不完整")
    return record


def load_development_bundle(cfg, output: Path, directory: Path):
    import numpy as np
    import pandas as pd
    from config import CLASS_ORDER
    from data_loader import DevelopmentData, write_json
    from deployment.lab_registry import SPLIT_SHA, sha256

    record = bundle_metadata(directory)
    if sha256(cfg.split_manifest_path) != SPLIT_SHA:
        raise ValueError("固定640/161划分清单摘要不符")
    split = json.loads(cfg.split_manifest_path.read_text(encoding="utf-8"))
    ids, labels = record["sample_ids"], record["labels"]
    if ids != split["development_ids"] or set(ids) & set(split["reserved_test_ids"]):
        raise ValueError("开发包样本顺序与固定划分不一致或包含保留样本")
    matrix_path = directory / "development.npy"
    if sha256(matrix_path) != record.get("matrix_file_sha256"):
        raise ValueError("开发矩阵文件摘要不符")
    values = np.load(matrix_path, mmap_mode="r", allow_pickle=False)
    if values.shape != (640, 20531) or values.dtype != np.dtype("<f8") or not values.flags.c_contiguous:
        raise ValueError("开发矩阵形状、float64精度或内存布局不符")
    if set(labels) != set(CLASS_ORDER):
        raise ValueError("开发包类别记录不符")
    digest = hashlib.sha256()
    digest.update(json.dumps(record["gene_ids"]).encode("utf-8"))
    for sid, label, row in zip(ids, labels, values):
        if not np.isfinite(row).all():
            raise ValueError("开发矩阵存在缺失或无穷值")
        digest.update(json.dumps([sid, label]).encode("utf-8"))
        digest.update(np.asarray(row, dtype="<f8").tobytes())
    if digest.hexdigest() != DEVELOPMENT_SHA:
        raise ValueError("实际开发表达值/标签与历史固定指纹不一致")
    X = pd.DataFrame(values, index=pd.Index(ids, name="sample_id"), columns=record["gene_ids"], copy=False)
    y = pd.Series(labels, index=X.index, name="cancer_type", dtype=str)
    write_json(output / "development_data_record.json", {
        "source": {"format": "development_only_npy_mmap", "matrix_sha256": record["matrix_file_sha256"]},
        "n_development": 640, "n_features": 20531, "n_reserved_excluded": 161,
        "development_fingerprint_sha256": digest.hexdigest(),
        "original_dataset_fingerprint_from_manifest": split["dataset_fingerprint_sha256"],
        "reserved_values_analyzed": False, "reserved_labels_analyzed": False,
        "strict_development_rows_only_parsed": True, "development_only_bundle": True,
        "development_class_counts": {c: int(y.eq(c).sum()) for c in CLASS_ORDER},
    })
    write_json(output / "split_manifest.json", split)
    return DevelopmentData(X, y, tuple(split["reserved_test_ids"]), split["dataset_fingerprint_sha256"], cfg.split_manifest_path)


def load_lab_development(cfg, output: Path):
    directory = bundle_directory()
    if directory is not None:
        return load_development_bundle(cfg, output, directory)
    from data_loader import load_existing_development_data
    return load_existing_development_data(cfg, output, strict_rows_only=True)
