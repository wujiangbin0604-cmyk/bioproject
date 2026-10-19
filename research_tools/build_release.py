# -*- coding: utf-8 -*-
"""构建平铺、可独立运行的五癌种预测器发布候选ZIP。"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from deployment.model_loader import load_deployment_model

PACKAGE = ROOT / "deployment"
OUTPUT = ROOT / "gene_expression_classifier_release.zip"

RELEASE_FILES = (
    ".gitignore", "LICENSE_PENDING.md", "README.md", "input_validator.py",
    "model_loader.py", "predict.py", "validate_portable.py", "validate_deployment.py",
    "requirements.txt", "requirements-test.txt", "__init__.py",
    "models/M1_anova_top50.joblib", "models/M1_anova_top50.metadata.json",
    "models/M1_anova_top50_gene_manifest.csv",
    "examples/sample_input.csv", "examples/sample_prediction.json",
    "tests/test_deployment.py", "tests/test_portable_validation.py",
)
FORBIDDEN_COMPONENTS = {
    "local_validation", "test_tmp", "results", "data", "__pycache__", ".venv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    loaded = load_deployment_model()
    model_path = PACKAGE / "models" / "M1_anova_top50.joblib"
    metadata_path = PACKAGE / "models" / "M1_anova_top50.metadata.json"
    manifest_path = PACKAGE / "models" / "M1_anova_top50_gene_manifest.csv"
    if (len(loaded.feature_names), len(loaded.selected_gene_names)) != (20531, 50):
        raise RuntimeError("冻结模型结构核验失败，停止打包")
    if not all((PACKAGE / relative).is_file() for relative in RELEASE_FILES):
        missing = [relative for relative in RELEASE_FILES if not (PACKAGE / relative).is_file()]
        raise FileNotFoundError(f"发布清单文件缺失：{missing}")
    for relative in RELEASE_FILES:
        if FORBIDDEN_COMPONENTS.intersection(Path(relative).parts):
            raise RuntimeError(f"禁止文件进入发布包：{relative}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in RELEASE_FILES:
            source = PACKAGE / relative
            archive.write(source, arcname=Path(relative).as_posix())
    with zipfile.ZipFile(OUTPUT) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC校验失败：{bad}")
        names = set(archive.namelist())
        if names != {Path(item).as_posix() for item in RELEASE_FILES}:
            raise RuntimeError("ZIP内文件与发布白名单不一致")
    print(f"archive={OUTPUT}")
    print(f"files={len(RELEASE_FILES)}")
    print(f"zip_sha256={sha256(OUTPUT)}")
    print(f"model_sha256={sha256(model_path)}")
    print(f"metadata_sha256={sha256(metadata_path)}")
    print(f"manifest_sha256={sha256(manifest_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
