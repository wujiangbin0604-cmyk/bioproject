"""从当前工程按白名单导出运行包，所有冻结工件按原字节复制。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import zipfile

from cloud_deployment.verify import file_sha, verify_content

ROOT = Path(__file__).resolve().parents[1]


def build(release):
    from backend.app.services.results import FILES, RUNS, ResultsRepository
    from deployment.lab_registry import CUSTOM_SOURCE_SHA, model_statuses

    statuses = model_statuses()
    if len(statuses) != 6 or not all(item["available"] for item in statuses):
        raise RuntimeError("本机六模型必须先通过原有注册校验：" + json.dumps(statuses, ensure_ascii=False))
    destination = ROOT / "cloud_deployment" / "dist" / release
    archive = destination.with_suffix(".zip")
    if destination.exists() or archive.exists():
        raise FileExistsError("发布目录已存在；使用新的--release名称，避免覆盖旧包")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise FileNotFoundError("先在项目根目录执行npm --prefix frontend run build")
    destination.mkdir(parents=True)
    original_sources = {}

    def copy(source, relative):
        source = source.resolve()
        if not source.is_relative_to(ROOT) or source.is_symlink() or not source.is_file():
            raise ValueError(f"源文件无效：{source}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest = file_sha(source)
        if file_sha(target) != digest:
            raise ValueError("复制后摘要发生变化")
        original_sources[str(source.relative_to(ROOT)).replace("\\", "/")] = digest

    for file in ROOT.glob("*.py"):
        copy(file, file.name)
    for file in (ROOT / "backend/app").rglob("*.py"):
        copy(file, file.relative_to(ROOT))
    for file in (ROOT / "deployment").glob("*.py"):
        copy(file, file.relative_to(ROOT))
    for folder in ("deployment/models", "deployment/lab_models"):
        for file in (ROOT / folder).iterdir():
            if file.is_file() and (file.suffix == ".joblib" or file.name.endswith(".metadata.json")):
                copy(file, file.relative_to(ROOT))
    copy(ROOT / "deployment/examples/sample_input.csv", "deployment/examples/sample_input.csv")
    copy(ROOT / "backend/requirements-web-runtime.lock.txt", "backend/requirements-web-runtime.lock.txt")
    # v2 imports the registry even when this legacy preview explicitly disables training.
    copy(ROOT / "datasets/registry.json", "datasets/registry.json")
    cloud_files = ("__init__.py", "requirements-cloud.lock.txt", "serve.py", "verify.py", "nginx.conf", "README.md")
    for name in cloud_files:
        copy(ROOT / "cloud_deployment" / name, Path("cloud_deployment") / name)
    copy(ROOT / "cloud_deployment/Dockerfile", "Dockerfile")
    copy(ROOT / "cloud_deployment/compose.yaml", "compose.yaml")
    for file in (ROOT / "frontend/dist").rglob("*"):
        if file.is_file():
            copy(file, file.relative_to(ROOT))
    repo = ResultsRepository(ROOT)
    for key, spec in RUNS.items():
        run = repo._run(key)
        if run is None:
            raise FileNotFoundError(f"历史运行指针不可用：{key}")
        new_run = f"history/{key}"
        (destination / "results" / new_run).mkdir(parents=True, exist_ok=True)
        # 只改上传副本中的定位路径，使其在Linux下使用POSIX目录；研究数值文件不改写。
        pointer = {"status": "complete", "run_directory": new_run,
                   "source_pointer_sha256": file_sha(ROOT / "results" / spec["pointer"])}
        (destination / "results" / spec["pointer"]).write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
        original_sources[f"results/{spec['pointer']}"] = pointer["source_pointer_sha256"]
    for file_key, spec in FILES.items():
        source = repo._file(file_key)
        copy(source, Path("results/history") / spec["run"] / spec["path"])
    for method in ("variance", "anova"):
        source = repo.heatmap_path(method)
        copy(source, Path("results/history/heatmaps/生成图片") / source.name)
    for name, expected in CUSTOM_SOURCE_SHA.items():
        if file_sha(destination / name) != expected:
            raise ValueError(f"自定义类型源码原字节摘要不符：{name}")
    (destination / ".dockerignore").write_text(
        ".git\n.env\n.env.*\n**/__pycache__\n**/*.pyc\n**/node_modules\n**/.vendor*\n*.zip\n**/*.tar\n**/*.tar.gz\ndata/\n", encoding="utf-8")
    metadata = {"schema_version": 1, "release": release, "created_at": datetime.now(timezone.utc).isoformat(),
                "scope": "private_preview_history_and_frozen_inference", "training_enabled": False,
                "raw_expression_data_included": False, "test_set_reevaluated": False,
                "models": statuses, "original_source_sha256": original_sources,
                "files": {str(file.relative_to(destination)).replace("\\", "/"): file_sha(file)
                          for file in sorted(destination.rglob("*")) if file.is_file()}}
    (destination / "bundle_manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    verify_content(destination)
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in sorted(destination.rglob("*")):
            if file.is_file():
                output.write(file, str(file.relative_to(destination)).replace("\\", "/"))
    checksum = file_sha(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size, "sha256": checksum,
                      "stage_directory": str(destination), "training_enabled": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", default="GeneScope_HK_preview_20261102_v3")
    args = parser.parse_args()
    if not args.release.replace("_", "").replace("-", "").isalnum() or len(args.release) > 100:
        raise ValueError("发布名只允许英文字母、数字、下划线和连字符")
    build(args.release)
