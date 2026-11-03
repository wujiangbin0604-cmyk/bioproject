"""从原固定划分导出完整640例开发矩阵，禁止输出保留样本的表达值和标签。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

from cloud_deployment.verify import file_sha


def export(destination: Path):
    import numpy as np
    from backend.app.lab_config import DEVELOPMENT_SHA
    from config import ExperimentConfig
    from data_loader import load_existing_development_data
    from deployment.lab_registry import SPLIT_SHA

    root = Path(__file__).resolve().parents[1]
    destination = destination.resolve()
    if not destination.is_relative_to(root / "cloud_deployment/dist") or destination.exists():
        raise ValueError("仅允许在新的cloud_deployment/dist子目录导出，防止覆盖已有资料")
    cfg = ExperimentConfig()
    if file_sha(cfg.split_manifest_path) != SPLIT_SHA:
        raise ValueError("原固定640/161划分摘要不符")
    destination.mkdir(parents=True)
    dev = load_existing_development_data(cfg, destination / "export_audit", strict_rows_only=True)
    audit = json.loads((destination / "export_audit/development_data_record.json").read_text(encoding="utf-8"))
    if audit["development_fingerprint_sha256"] != DEVELOPMENT_SHA:
        raise ValueError("原开发数据指纹不符")
    values = np.ascontiguousarray(dev.X.to_numpy(dtype="<f8", copy=False))
    matrix = destination / "development.npy"
    np.save(matrix, values, allow_pickle=False)
    metadata = {
        "schema_version": 1, "shape": [640, 20531], "dtype": "float64",
        "sample_ids": list(dev.X.index), "labels": dev.y.tolist(), "gene_ids": list(dev.X.columns),
        "matrix_file_sha256": file_sha(matrix), "development_fingerprint_sha256": DEVELOPMENT_SHA,
        "fixed_split_manifest_sha256": SPLIT_SHA, "reserved_expression_included": False,
        "reserved_labels_included": False, "preprocessing_fitted": False,
    }
    (destination / "development_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=3) as output:
        for name in ("development.npy", "development_metadata.json"):
            output.write(destination / name, name)
    digest = file_sha(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest,
                      "samples": 640, "genes": 20531, "development_sha256": DEVELOPMENT_SHA,
                      "reserved_expression_and_labels_exported": False}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    export(parser.parse_args().destination)
