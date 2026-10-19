# -*- coding: utf-8 -*-
"""验证发布目录中的模型工件、合成输入、API和命令行预测。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback

import joblib
import numpy as np
import pandas as pd
import sklearn

try:  # 支持作为包导入或直接运行此脚本
    from .input_validator import validate_single_sample
    from .model_loader import load_deployment_model
    from .predict import predict_single_sample
except ImportError:  # pragma: no cover - 直接运行时使用
    from input_validator import validate_single_sample
    from model_loader import load_deployment_model
    from predict import predict_single_sample

PACKAGE_DIR = Path(__file__).resolve().parent
MODEL_DIR = PACKAGE_DIR / "models"
EXAMPLE = PACKAGE_DIR / "examples" / "sample_input.csv"
REPORT_DIR = PACKAGE_DIR / "reports"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation_scope": "release package only; synthetic example only",
        "research_project_imports_used": False,
        "raw_training_data_required": False,
        "reserved_test_data_accessed": False,
        "model_training_performed": False,
        "status": "failed",
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    try:
        model = load_deployment_model()
        metadata_path = model.model_path.with_name(f"{model.model_path.stem}.metadata.json")
        manifest_path = MODEL_DIR / "M1_anova_top50_gene_manifest.csv"
        manifest = pd.read_csv(manifest_path, encoding="utf-8-sig")
        if len(model.feature_names) != 20531 or len(model.selected_gene_names) != 50:
            raise RuntimeError("模型特征数量与冻结配置不符")
        if not EXAMPLE.is_file():
            raise FileNotFoundError(f"缺少合成输入示例：{EXAMPLE.name}")

        input_frame = pd.read_csv(EXAMPLE, encoding="utf-8-sig")
        validated = validate_single_sample(input_frame, model.feature_names)
        direct_prediction = str(model.pipeline.predict(validated.features)[0])
        api_result = predict_single_sample(input_frame)
        if api_result["predicted_class"] != direct_prediction:
            raise RuntimeError("直接Pipeline与Python API预测不一致")

        with tempfile.TemporaryDirectory(prefix="portable_validation_", dir=REPORT_DIR) as temp:
            output_path = Path(temp) / "prediction.json"
            completed = subprocess.run(
                [sys.executable, str(PACKAGE_DIR / "predict.py"), "--input", str(EXAMPLE),
                 "--output", str(output_path)],
                cwd=PACKAGE_DIR, text=True, encoding="utf-8", errors="replace",
                capture_output=True, check=False, timeout=120,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"CLI预测失败：{completed.stderr.strip()}")
            cli_result = json.loads(output_path.read_text(encoding="utf-8"))
        if cli_result.get("predicted_class") != direct_prediction:
            raise RuntimeError("CLI与直接Pipeline预测不一致")
        expected_columns = set(model.feature_names) | {"sample_id"}
        if set(input_frame.columns) != expected_columns:
            raise RuntimeError("合成示例的列与完整特征清单不一致")
        required_manifest_columns = {"gene_id", "selected_by_M1", "selected_gene_order"}
        if len(manifest) != 20531 or not required_manifest_columns.issubset(manifest.columns):
            raise RuntimeError("基因清单行数或必需字段不完整")
        if tuple(manifest["gene_id"].astype(str)) != model.feature_names:
            raise RuntimeError("基因清单名称或顺序与冻结Pipeline不一致")
        manifest_selected = tuple(manifest.loc[manifest["selected_by_M1"].astype(bool), "gene_id"].astype(str))
        if manifest_selected != model.selected_gene_names:
            raise RuntimeError("基因清单选中标记与冻结Pipeline不一致")

        result.update({
            "status": "passed",
            "model_sha256": _sha256(model.model_path),
            "metadata_sha256": _sha256(metadata_path),
            "manifest_sha256": _sha256(manifest_path),
            "raw_feature_count": len(model.feature_names),
            "selected_feature_count": len(model.selected_gene_names),
            "manifest_matches_pipeline": True,
            "synthetic_example_columns": len(input_frame.columns),
            "pipeline_api_cli_predictions_match": True,
            "synthetic_prediction": direct_prediction,
            "prediction_is_performance_evidence": False,
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    output = REPORT_DIR / "portable_validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "passed":
        print(result.get("traceback", result.get("error", "portable validation failed")), file=sys.stderr)
        return 1
    print("portable validation passed")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
