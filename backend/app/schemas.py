"""Pydantic response contracts for the GeneScope API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class APIEnvelope(BaseModel):
    status: Literal["available", "partial", "unavailable"]
    source: str | None = None
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class HealthData(BaseModel):
    api: str
    results_available: bool
    model_available: bool
    model_name: str
    model_version: str
    model_unavailable_reason: str | None = None
    python_version: str


class PredictionData(BaseModel):
    sample_id: str | None = None
    predicted_class: str
    model_name: str
    model_version: str
    input_feature_count: int
    selected_feature_count: int
    input_columns_reordered: bool
    inference_status: Literal["success"]
    probability_output: Literal[False] = False
    interpretation_notice: str


class PredictionResponse(BaseModel):
    status: Literal["success"]
    data: PredictionData


class APIErrorBody(BaseModel):
    code: str
    message: str


class APIErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error: APIErrorBody
