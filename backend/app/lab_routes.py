"""模型实验室：现场冻结推理、独立CV工作进程、可恢复连接的SSE快照。"""
from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend.app.lab_config import PROJECT, TERMINAL, ExperimentRequest, limits
from backend.app.services.lab_jobs import LabJobs, TaskConflict
from backend.app.services.predictor import validate_upload, InputValidationError, UploadValidationError
from deployment.lab_registry import model_statuses, predict_registered

router = APIRouter(prefix="/api/v1/lab", tags=["Interactive laboratory"])


def local_mutation(request: Request):
    # 实验接口为本机研究工作台。浏览器站点不能跨来源消耗训练资源。
    from backend.app.main import _origins
    allowed = set(_origins()) | {str(request.base_url).rstrip("/")}
    origin = request.headers.get("origin")
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"} or (origin and origin.rstrip("/") not in allowed):
        raise HTTPException(403, "实验室写操作仅允许本机及明确配置的来源")


def jobs(request: Request) -> LabJobs:
    return request.app.state.lab_jobs


def get_state(request, task_id):
    try:
        return jobs(request).get(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "任务不存在") from exc


@router.get("/models")
def models():
    return {"source": "verified_frozen_artifact_registry", "models": model_statuses()}


@router.post("/predict")
def predict(request: Request, file: UploadFile = File(...), model_ids: str = Form(...)):
    local_mutation(request)
    try:
        ids = json.loads(model_ids)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(422, "model_ids必须是模型ID数组的JSON") from exc
    if not isinstance(ids, list) or not 1 <= len(ids) <= 6 or any(type(x) is not str or x not in {f"M{i}" for i in range(6)} for x in ids) or len(set(ids)) != len(ids):
        raise HTTPException(422, "请选择1–6个不重复的M0–M5模型")
    try:
        payload = file.file.read(5 * 1024 * 1024 + 1)
    finally:
        file.file.close()
    if not (file.filename or "").lower().endswith(".csv") or len(payload) > 5*1024*1024:
        raise HTTPException(422, "只接受最高5 MiB的CSV")
    try:
        frame = validate_upload(payload)
    except (InputValidationError, UploadValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    # 一次提交内每个模型独立执行predict；单模型失败不伪造其类别。
    return predict_registered(frame, ids)


@router.get("/capabilities")
def capabilities(request: Request):
    from config import ExperimentConfig
    from deployment.lab_registry import SPLIT_SHA, sha256
    cfg = ExperimentConfig()
    reason = None
    try:
        if os.environ.get("GENESCOPE_LAB_TRAINING_ENABLED", "1") != "1":
            raise ValueError("当前部署阶段开放历史展示与冻结模型推理，现场训练尚未启用。")
        if request.app.state.results.root != PROJECT:
            raise ValueError("隔离测试/备用结果目录不启用现场训练")
        if not cfg.split_manifest_path.is_file() or sha256(cfg.split_manifest_path) != SPLIT_SHA:
            raise ValueError("固定划分清单缺失或摘要不符")
        from backend.app.services.development_data import bundle_directory, bundle_metadata
        directory = bundle_directory()
        if directory is not None:
            bundle_metadata(directory)
        elif not (cfg.raw_archive.is_file() or ((cfg.data_dir / "data.csv").is_file() and (cfg.data_dir / "labels.csv").is_file())):
            raise ValueError("640例开发数据尚未配置；不提供模拟训练")
    except Exception as exc:
        reason = str(exc)
    return {"available": reason is None, "reason": reason, "limits": limits(),
            "classifiers": ["linear_svm", "logistic_regression"], "selections": ["all", "anova", "variance"],
            "k_values": [20, 50, 100, 300, 500, 1000], "c_values": [0.1, 1.0, 10.0],
            "cv_modes": ["standard", "repeated"], "scope": "fixed_640_development_only"}


@router.get("/tasks")
def list_tasks(request: Request):
    return {"tasks": jobs(request).list()}


@router.post("/tasks", status_code=202)
def create_task(configuration: ExperimentRequest, request: Request):
    local_mutation(request)
    capability = capabilities(request)
    if not capability["available"]:
        raise HTTPException(503, capability["reason"])
    try:
        return jobs(request).start(configuration)
    except TaskConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/tasks/{task_id}")
def task(request: Request, task_id: str):
    return get_state(request, task_id)


@router.post("/tasks/{task_id}/cancel")
def cancel(request: Request, task_id: str):
    local_mutation(request)
    get_state(request, task_id)
    try:
        return jobs(request).cancel(task_id)
    except TaskConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/tasks/{task_id}/events")
async def events(request: Request, task_id: str):
    get_state(request, task_id)

    async def stream():
        previous = -1
        heartbeat = 0
        yield "retry: 1500\n\n"
        while not await request.is_disconnected():
            state = await asyncio.to_thread(get_state, request, task_id)
            if state["revision"] != previous or heartbeat % 3 == 0:
                yield f"id: {state['revision']}\nevent: snapshot\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
                previous = state["revision"]
            if state["status"] in TERMINAL:
                break
            heartbeat += 1
            if heartbeat % 15 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/tasks/{task_id}/export")
def export(request: Request, task_id: str):
    state = get_state(request, task_id)
    directory = jobs(request).directory(task_id)
    content = io.BytesIO()
    names = ("configuration.json", "environment.json", "fold_results.csv", "round_results.csv", "per_class_metrics.csv",
             "oof_predictions.csv", "selected_features.csv", "fit_audit.csv", "cv_indices.json", "summary.json", "development_data_record.json", "resource_usage.json")
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("state.json", json.dumps(state, ensure_ascii=False, indent=2))
        for filename in names:
            path = directory / filename
            if path.is_file():
                archive.write(path, filename)
    return Response(content.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="genescope_lab_{task_id}.zip"'})
