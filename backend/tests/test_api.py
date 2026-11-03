"""API contract tests use temporary fixtures and never stand in for research results."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services.predictor import PredictionError


CLASSES = ("BRCA", "KIRC", "COAD", "LUAD", "PRAD")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        project_root=tmp_path,
        predictor=lambda frame: {"predicted_class": "BRCA"},
        model_status_getter=lambda: {"available": False, "reason": "测试夹具中的环境版本不匹配"},
    )
    return TestClient(app)


def test_health_and_missing_results_degrade_gracefully(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    status = client.get("/api/v1/experiments/status")

    assert health.status_code == 200
    assert health.json()["status"] == "partial"
    assert health.json()["data"]["model_available"] is False
    assert status.status_code == 200
    assert status.json()["data"]["available_count"] == 0
    assert status.json()["data"]["patient_level_outputs_exposed"] is False


def test_project_metadata_has_five_documented_classes(client: TestClient) -> None:
    response = client.get("/api/v1/project/meta")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["samples"] == 801
    assert payload["features"] == 20531
    assert [item["code"] for item in payload["classes"]] == list(CLASSES)


def test_openapi_and_swagger_docs_are_available(client: TestClient) -> None:
    openapi = client.get("/openapi.json")
    docs = client.get("/docs")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "GeneScope API"
    assert docs.status_code == 200


def test_bad_model_id_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/models/confusion-matrix", params={"model_id": "M9"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_model_id"


def test_non_csv_upload_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/predict", files={"file": ("sample.txt", b"x,y\n1,2\n")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_upload_size_limit_is_enforced(client: TestClient) -> None:
    response = client.post("/api/v1/predict", files={"file": ("large.csv", b"x" * (5 * 1024 * 1024 + 1))})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize(
    "payload",
    [
        b"gene_0,gene_1\n1,2\n",
        b"gene_0,gene_0\n1,2\n",
    ],
    ids=("missing-genes", "duplicate-genes"),
)
def test_missing_or_duplicate_gene_columns_are_rejected(client: TestClient, payload: bytes) -> None:
    response = client.post("/api/v1/predict", files={"file": ("sample.csv", payload, "text/csv")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_invalid_result_json_is_reported_as_unavailable(tmp_path: Path) -> None:
    results = tmp_path / "results"
    run = results / "baseline-run"
    run.mkdir(parents=True)
    (results / "latest_stage1.json").write_text(
        json.dumps({"status": "complete", "run_directory": "baseline-run"}), encoding="utf-8"
    )
    (run / "data_quality.json").write_text("[]", encoding="utf-8")
    response = TestClient(create_app(project_root=tmp_path,
                                    predictor=lambda frame: {},
                                    model_status_getter=lambda: {"available": False})).get(
                                        "/api/v1/dataset/summary")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "result_format_error"


def test_model_environment_mismatch_is_explicit(tmp_path: Path) -> None:
    def unavailable(_: object) -> dict[str, object]:
        raise PredictionError("模型运行环境版本不匹配：Python 3.14.0")

    app = create_app(project_root=tmp_path, predictor=unavailable,
                     model_status_getter=lambda: {"available": False, "reason": "Python版本不匹配"})
    csv_header = ",".join(f"gene_{i}" for i in range(20531))
    csv_row = ",".join("0" for _ in range(20531))
    response = TestClient(app).post(
        "/api/v1/predict", files={"file": ("sample.csv", f"{csv_header}\n{csv_row}\n".encode(), "text/csv")}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert "3.14.0" in response.json()["error"]["message"]
