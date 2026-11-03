"""在本机匹配环境验证导出后的独立目录；不能替代Linux容器验收。"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    stage = args.stage.resolve()
    if not stage.is_relative_to(source / "cloud_deployment/dist"):
        raise ValueError("只能检查本项目导出的部署目录")
    sys.path.insert(0, str(stage))
    os.environ["GENESCOPE_LAB_TRAINING_ENABLED"] = "0"
    from cloud_deployment.verify import file_sha, verify_content
    from deployment.lab_registry import ROOT as loaded_root, model_statuses, predict_registered
    from backend.app.services.predictor import validate_upload
    from backend.app.services.results import ResultsRepository
    if loaded_root != stage:
        raise RuntimeError("错误地载入了源工作区模块，拒绝把它当作独立包验证")
    metadata = verify_content(stage)
    statuses = model_statuses()
    assert len(statuses) == 6 and all(row["available"] for row in statuses), statuses
    repository = ResultsRepository(stage)
    status = repository.experiment_status()
    assert status["available_count"] == 8 and status["heatmaps_available"]
    assert repository.dataset_summary()["dataset"]["samples"] == 801
    assert len(repository.feature_performance("anova")["records"]) == 6
    repository.feature_stability("anova", 50)
    repository.feature_genes("anova", 50, "", 1, 25, "selection_frequency", True, False)
    assert len(repository.model_comparison()["models"]) == 6
    repository.model_per_class("M1")
    assert repository.model_confusion("M1")["sample_count"] == 161  # 仅读取已保存矩阵计数。
    repository.model_error_analysis()
    repository.fusion_summary()
    assert not any(stage.rglob("data.csv")) and not any(stage.rglob("labels.csv"))
    assert not any(stage.rglob("*.tar"))
    sample = source / "deployment/examples/local_validation/dev_sample_input.csv"
    with sample.open(encoding="utf-8-sig", newline="") as stream:
        record = next(csv.DictReader(stream))
    split = json.loads((source / "data/split_manifest.json").read_text(encoding="utf-8"))
    assert record["sample_id"] in split["development_ids"] and record["sample_id"] not in split["reserved_test_ids"]
    result = predict_registered(validate_upload(sample.read_bytes()), [f"M{i}" for i in range(6)])
    assert all(row["status"] == "success" for row in result["results"]), result
    for relative, original_sha in metadata["original_source_sha256"].items():
        assert file_sha(source / relative) == original_sha, f"源文件改变：{relative}"
    report = {"scope": "windows_staged_package_validation_not_linux_validation", "models": statuses,
              "historical_sections_available": status["available_count"], "development_sample_inference": result,
              "original_source_hashes_unchanged": True, "raw_expression_data_included": False,
              "training_enabled": False, "test_set_reevaluated": False,
              "linux_container_build_and_runtime": "pending_server_verification"}
    path = stage.with_suffix(".validation.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(path), "models_available": len(statuses),
                      "historical_sections_available": 8, "inference_successes": len(result["results"]),
                      "linux_runtime_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
