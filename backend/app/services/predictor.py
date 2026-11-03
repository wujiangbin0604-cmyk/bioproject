"""Bridge web uploads to the frozen deployment validator and M1 prediction API."""
from __future__ import annotations

import csv
from functools import lru_cache
import io
from pathlib import Path
from typing import Any

import pandas as pd

from deployment.input_validator import InputValidationError, validate_single_sample
from deployment.predict import PredictionError, predict_single_sample
from deployment.model_loader import ModelArtifactError, load_deployment_model


EXPECTED_FEATURES = tuple(f"gene_{index}" for index in range(20531))
MODEL_NAME = "ANOVA Top50 + LinearSVC"
MODEL_VERSION = "M1-anova50-linearsvc-1.0.0"


class UploadValidationError(ValueError):
    """The uploaded in-memory CSV is invalid."""


@lru_cache(maxsize=1)
def model_environment_status() -> dict[str, Any]:
    """Use the existing verified model loader; never weaken its version or hash checks."""
    import platform

    try:
        loaded = load_deployment_model()
        return {"available": True, "reason": None,
                "model_name": loaded.metadata.get("model_name", MODEL_NAME),
                "model_version": loaded.metadata.get("model_version", MODEL_VERSION),
                "python_version": platform.python_version()}
    except ModelArtifactError as exc:
        # Loader diagnostics intentionally remain visible (e.g. version mismatch),
        # while filesystem paths and internal stack details stay server-side.
        message = str(exc).replace(str(Path(__file__).resolve().parents[3]), "项目目录")
        return {"available": False, "reason": message, "model_name": MODEL_NAME,
                "model_version": MODEL_VERSION, "python_version": platform.python_version()}
    except Exception as exc:  # dependency/import issues are actionable, stack is not public
        return {"available": False,
                "reason": f"预测环境不可用：{type(exc).__name__}。请按 deployment/requirements.txt 安装并使用 Python 3.14.0。",
                "model_name": MODEL_NAME, "model_version": MODEL_VERSION,
                "python_version": platform.python_version()}


def parse_uploaded_csv(payload: bytes) -> pd.DataFrame:
    """Parse one row in memory while preserving duplicate header names for the validator."""
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadValidationError("请使用UTF-8或UTF-8 BOM编码的CSV文件") from exc
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header:
            raise UploadValidationError("CSV缺少表头")
        if len(header) > 20532:
            raise UploadValidationError("输入字段超过20532列；只允许20531个基因列和可选sample_id")
        rows = [row for row in reader if row and any(str(cell).strip() for cell in row)]
    except csv.Error as exc:
        raise UploadValidationError("CSV格式无法解析，请检查引号和分隔符") from exc
    if len(rows) != 1:
        raise UploadValidationError(f"单样本预测要求恰好1行数据，实际为{len(rows)}行")
    if len(rows[0]) != len(header):
        raise UploadValidationError("数据行字段数量与CSV表头不一致")
    # Assign raw header names after parsing so pandas cannot silently rename duplicates.
    frame = pd.DataFrame([rows[0]])
    frame.columns = header
    return frame


def validate_upload(payload: bytes) -> pd.DataFrame:
    """Run the existing deployment validator against the upload; this only holds data in memory."""
    frame = parse_uploaded_csv(payload)
    validate_single_sample(frame, EXPECTED_FEATURES)
    return frame


def predict_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Invoke the repository's existing prediction function and trusted model loader."""
    return predict_single_sample(frame)


__all__ = [
    "EXPECTED_FEATURES", "InputValidationError", "PredictionError", "UploadValidationError",
    "model_environment_status", "parse_uploaded_csv", "predict_frame", "validate_upload",
]
