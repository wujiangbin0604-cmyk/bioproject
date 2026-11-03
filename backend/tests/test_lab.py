"""实验室契约与隔离测试；夹具不是实验成绩，不训练分类模型。"""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.main import create_app
from backend.app.lab_config import ExperimentRequest, atomic_json
from backend.app.services.lab_jobs import LabJobs, TaskConflict
from deployment import lab_registry
from deployment.model_loader import ModelArtifactError


def client_for(root):
    return TestClient(create_app(project_root=root), client=("127.0.0.1", 45678))


@pytest.mark.parametrize("arguments", [{"k": 51}, {"c": 5}, {"classifier": "python"}, {"data_path": "test.csv"}, {"n_splits": 10}])
def test_only_controlled_configurations(arguments):
    with pytest.raises(ValidationError):
        ExperimentRequest(**arguments)


def test_all_features_has_canonical_configuration():
    assert ExperimentRequest(selection="all", k=20).k == 50


@pytest.mark.parametrize("classifier", ["linear_svm", "logistic_regression"])
@pytest.mark.parametrize("selection", ["all", "anova", "variance"])
def test_all_preset_pipelines_are_cloneable_and_keep_step_order(classifier, selection):
    from sklearn.base import clone
    from backend.app.lab_worker import build_pipeline
    pipeline = clone(build_pipeline(ExperimentRequest(classifier=classifier, selection=selection, c=.1)))
    assert list(pipeline.named_steps) == (["scale", "model"] if selection == "all" else ["select", "scale", "model"])
    assert pipeline.named_steps["model"].C == .1
    assert pipeline.named_steps["model"].random_state == 42
    if classifier == "logistic_regression":
        assert pipeline.named_steps["model"].solver == "lbfgs"


def test_untrusted_pickle_rejected_before_deserialization(tmp_path, monkeypatch):
    monkeypatch.setattr(lab_registry, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(lab_registry, "CUSTOM_SOURCE_SHA", {})
    monkeypatch.setattr(lab_registry, "check_environment", lambda: None)
    (tmp_path / "M0.joblib").write_bytes(b"untrusted pickle")
    called = []
    monkeypatch.setattr(lab_registry.joblib, "load", lambda *_: called.append(True))
    lab_registry.load_registered.cache_clear()
    with pytest.raises(ModelArtifactError, match="SHA-256"):
        lab_registry.load_registered("M0")
    assert not called


def test_lab_never_enables_training_with_missing_fixed_data(tmp_path):
    client = client_for(tmp_path)
    capability = client.get("/api/v1/lab/capabilities").json()
    assert not capability["available"]
    assert client.post("/api/v1/lab/tasks", json={}).status_code == 503
    assert not (tmp_path / "results" / "lab_experiments").exists()


def test_cloud_preview_explicitly_disables_training(tmp_path, monkeypatch):
    monkeypatch.setenv("GENESCOPE_LAB_TRAINING_ENABLED", "0")
    client = client_for(tmp_path)
    capability = client.get("/api/v1/lab/capabilities").json()
    assert not capability["available"] and "尚未启用" in capability["reason"]
    assert client.post("/api/v1/lab/tasks", json={}).status_code == 503
    assert not (tmp_path / "results" / "lab_experiments").exists()


def test_cross_origin_training_is_rejected(tmp_path):
    client = client_for(tmp_path)
    assert client.post("/api/v1/lab/tasks", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403


def test_process_lock_is_shared_across_managers(tmp_path):
    first, second = LabJobs(tmp_path), LabJobs(tmp_path)
    guard = first._acquire()
    try:
        with pytest.raises(TaskConflict):
            second._acquire()
    finally:
        guard.close()
    second._acquire().close()


def test_sse_terminal_snapshot_export_and_missing_id(tmp_path):
    client = client_for(tmp_path)
    task_id = "a" * 32
    directory = tmp_path / "results" / "lab_experiments" / task_id
    state = {"task_id": task_id, "status": "cancelled", "revision": 3,
             "created_at": datetime.now(timezone.utc).isoformat(), "configuration": {}, "completed_folds": 0}
    atomic_json(directory / "state.json", state)
    (directory / "split_manifest.json").write_text('{"reserved_test_ids":["PRIVATE"]}', encoding="utf-8")
    (directory / "fold_results.csv").write_text("fold_id\n", encoding="utf-8")
    stream = client.get(f"/api/v1/lab/tasks/{task_id}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: snapshot" in stream.text and '"status": "cancelled"' in stream.text
    exported = client.get(f"/api/v1/lab/tasks/{task_id}/export")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert "state.json" in archive.namelist()
        assert "split_manifest.json" not in archive.namelist()
    assert client.get("/api/v1/lab/tasks/not-a-task").status_code == 404


def test_invalid_upload_cannot_reach_predictor(tmp_path, monkeypatch):
    from backend.app import lab_routes
    invoked = []
    monkeypatch.setattr(lab_routes, "predict_registered", lambda *_: invoked.append(True))
    response = client_for(tmp_path).post("/api/v1/lab/predict", data={"model_ids": '["M1"]'},
                                       files={"file": ("wrong.csv", b"gene_0\n1\n", "text/csv")})
    assert response.status_code == 422 and not invoked
