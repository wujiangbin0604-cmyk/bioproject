"""校验上传包字节完整性及原冻结加载器；没有fit、测试集预测或评分。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_content(root):
    root = Path(root).resolve()
    metadata = json.loads((root / "bundle_manifest.json").read_text(encoding="utf-8"))
    if metadata.get("training_enabled") is not False or metadata.get("raw_expression_data_included") is not False:
        raise ValueError("本预览包范围标记错误")
    for relative, expected in metadata["files"].items():
        part = PurePosixPath(relative)
        if part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
            raise ValueError("上传清单存在不安全路径")
        path = (root / Path(*part.parts)).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink() or file_sha(path) != expected:
            raise ValueError(f"上传包文件缺失或摘要不同：{relative}；请重新传输原包，不修改可信摘要")
    print(f"Bundle content: OK ({len(metadata['files'])} files)", flush=True)
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true", help="调用既有冻结加载器，验证全部六个模型")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    verify_content(root)
    if args.models:
        from deployment.lab_registry import model_statuses
        statuses = model_statuses()
        print(json.dumps(statuses, ensure_ascii=False, indent=2), flush=True)
        if len(statuses) != 6 or not all(model["available"] for model in statuses):
            raise RuntimeError("冻结模型验证未全部通过，停止部署；不重训、不绕过校验")


if __name__ == "__main__":
    main()
