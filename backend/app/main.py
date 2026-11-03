"""GeneScope API: read-only experiment summaries plus the frozen M1 upload endpoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
import os
from pathlib import Path
import platform
import time
from typing import Any, Callable

from fastapi import FastAPI, File, Form, Query, Request, UploadFile, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .schemas import APIEnvelope, APIErrorResponse, HealthData, PredictionResponse
from deployment.model_loader import ModelArtifactError

from .services.predictor import (InputValidationError, PredictionError, UploadValidationError,
                                 model_environment_status, predict_frame, validate_upload)
from .services.results import (PROJECT_ROOT, ResultFormatError, ResultUnavailable,
                               ResultsRepository, CLASS_LABELS)

logger = logging.getLogger("genescope.api")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def _origins() -> list[str]:
    raw = os.environ.get("GENESCOPE_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("GENESCOPE_ALLOWED_ORIGINS must contain explicit origins and cannot use '*'")
    return origins


def create_app(project_root: Path | str = PROJECT_ROOT,
               predictor: Callable[[Any], dict[str, Any]] | None = None,
               model_status_getter: Callable[[], dict[str, Any]] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(api):
        try:
            yield
        finally:
            api.state.lab_jobs.shutdown()
            api.state.platform_jobs.shutdown()

    app = FastAPI(
        title="GeneScope API",
        description="Multi-dataset experiments, supervised subprocess tasks, SSE progress and trusted model prediction; legacy research results stay read-only.",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.results = ResultsRepository(project_root)
    app.state.predictor = predictor or predict_frame
    app.state.model_status_getter = model_status_getter or model_environment_status
    from .services.lab_jobs import LabJobs
    from .lab_routes import router as lab_router
    from .lab_config import task_root
    app.state.lab_jobs = LabJobs(task_root(Path(project_root)))
    app.include_router(lab_router)
    from .platform2.data import Datasets
    from .platform2.jobs import Jobs
    from .platform2.routes import router as platform_router
    app.state.datasets = Datasets(project_root)
    app.state.platform_jobs = Jobs(project_root)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
    )

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"status": "error", "error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(item) for item in first.get("loc", ()) if item != "query")
        message = f"请求参数无效：{field or '请检查参数格式'}"
        return JSONResponse(status_code=422,
                            content={"status": "error", "error": {"code": "request_validation_failed", "message": message}})

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"status":"error", "detail":exc.detail,
                            "error":{"code":f"http_{exc.status_code}","message":str(exc.detail)}})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error: %s", type(exc).__name__)
        return JSONResponse(status_code=500,
                            content={"status": "error", "error": {"code": "internal_error", "message": "服务内部处理失败，请查看后端日志。"}})

    def envelope(method: Callable[..., dict[str, Any]], *args: Any, source: str,
                 unavailable_message: str | None = None, **kwargs: Any) -> dict[str, Any]:
        try:
            data = method(*args, **kwargs)
            return {"status": "available", "source": source, "message": None, "data": data}
        except ResultUnavailable as exc:
            return {"status": "unavailable", "source": source,
                    "message": unavailable_message or str(exc), "data": {}}
        except ResultFormatError as exc:
            raise APIError(503, "result_format_error", str(exc)) from exc
        except ValueError as exc:
            raise APIError(422, "invalid_query", str(exc)) from exc

    @app.get("/api/v1/health", response_model=APIEnvelope)
    async def health() -> dict[str, Any]:
        repo = app.state.results
        try:
            experiments = repo.experiment_status()
            results_available = experiments["available_count"] > 0
        except ResultFormatError:
            results_available = False
        model = app.state.model_status_getter()
        data = HealthData(api="ok", results_available=results_available,
                          model_available=bool(model.get("available")),
                          model_name=str(model.get("model_name", "ANOVA Top50 + LinearSVC")),
                          model_version=str(model.get("model_version", "M1-anova50-linearsvc-1.0.0")),
                          model_unavailable_reason=model.get("reason"),
                          python_version=str(model.get("python_version", platform.python_version())))
        return {"status": "available" if results_available else "partial", "source": "项目运行时状态",
                "message": None if data.model_available else "研究结果可浏览；单样本预测模型环境当前不可用。",
                "data": data.model_dump()}

    @app.get("/api/v1/project/meta", response_model=APIEnvelope)
    async def project_meta() -> dict[str, Any]:
        return {"status": "available", "source": "项目配置与数据集定义", "message": None,
                "data": {"name": "GeneScope", "subtitle": "RNA-Seq Cancer Classification & Feature Analysis",
                         "dataset": "UCI Gene Expression Cancer RNA-Seq Dataset 401",
                         "samples": 801, "features": 20531, "development_samples": 640,
                         "retrospective_holdout_samples": 161,
                         "classes": [{"code": code, "label": label} for code, label in CLASS_LABELS.items()],
                         "research_scope": "五类已患癌肿瘤的表达类别分类；不提供患癌风险、筛查或临床诊断。"}}

    @app.get("/api/v1/experiments/status", response_model=APIEnvelope)
    async def experiment_status() -> dict[str, Any]:
        return envelope(app.state.results.experiment_status, source="本地已保存实验汇总文件")

    @app.get("/api/v1/dataset/summary", response_model=APIEnvelope)
    async def dataset_summary() -> dict[str, Any]:
        return envelope(app.state.results.dataset_summary, source="数据质量与类别统计报告")

    @app.get("/api/v1/dataset/heatmaps", response_model=APIEnvelope)
    async def dataset_heatmaps() -> dict[str, Any]:
        items = []
        for method, label in (("variance", "开发集高方差Top50"), ("anova", "开发集ANOVA Top50")):
            try:
                app.state.results.heatmap_path(method)
                items.append({"method": method, "name": label, "status": "available",
                              "url": f"/api/v1/dataset/heatmaps/{method}", "scope": "640例开发集探索性可视化",
                              "sample_order": "预设癌种排序，不是聚类结果",
                              "standardization": "基因行方向Z-score"})
            except ResultUnavailable:
                items.append({"method": method, "name": label, "status": "unavailable", "url": None,
                              "scope": "640例开发集探索性可视化"})
        available = any(item["status"] == "available" for item in items)
        return {"status": "available" if available else "unavailable", "source": "项目已保存的真实热图PNG",
                "message": None if available else "热图结果尚未导入。", "data": {"images": items}}

    @app.get("/api/v1/dataset/heatmaps/{method}")
    async def heatmap_image(method: str) -> FileResponse:
        try:
            path = app.state.results.heatmap_path(method)
        except ValueError as exc:
            raise APIError(404, "unknown_heatmap", "未知热图方法。") from exc
        except ResultUnavailable as exc:
            raise APIError(404, "heatmap_unavailable", str(exc)) from exc
        return FileResponse(path, media_type="image/png", filename=f"genescope_{method}_top50.png")

    @app.get("/api/v1/features/performance", response_model=APIEnvelope)
    async def feature_performance(method: str = Query("all"), k: int | None = Query(None, ge=20, le=20531)) -> dict[str, Any]:
        return envelope(app.state.results.feature_performance, method, k, source="开发集重复分层交叉验证结果")

    @app.get("/api/v1/features/stability", response_model=APIEnvelope)
    async def feature_stability(method: str = Query("all"), k: int | None = Query(None, ge=20, le=1000)) -> dict[str, Any]:
        return envelope(app.state.results.feature_stability, method, k, source="开发集30次共享分层子采样结果")

    @app.get("/api/v1/features/genes", response_model=APIEnvelope)
    async def feature_genes(method: str = Query("anova"), k: int = Query(50), search: str = Query("", max_length=64),
                            page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                            sort_by: str = Query("selection_frequency"), descending: bool = Query(True),
                            include_zero: bool = Query(False)) -> dict[str, Any]:
        return envelope(app.state.results.feature_genes, method, k, search, page, page_size, sort_by, descending,
                        include_zero, source="30次共享分层子采样基因入选频率")

    @app.get("/api/v1/models/comparison", response_model=APIEnvelope)
    async def model_comparison() -> dict[str, Any]:
        return envelope(app.state.results.model_comparison, source="冻结模型的回顾性保留集评价")

    @app.get("/api/v1/models/per-class", response_model=APIEnvelope)
    async def model_per_class(model_id: str | None = Query(None)) -> dict[str, Any]:
        if model_id is not None and model_id not in {"M0", "M1", "M2", "M3", "M4", "M5"}:
            raise APIError(422, "invalid_model_id", "model_id必须为M0、M1、M2、M3、M4或M5")
        return envelope(app.state.results.model_per_class, model_id, source="回顾性保留集逐类别指标")

    @app.get("/api/v1/models/confusion-matrix", response_model=APIEnvelope)
    async def model_confusion(model_id: str = Query("M1")) -> dict[str, Any]:
        if model_id not in {"M0", "M1", "M2", "M3", "M4", "M5"}:
            raise APIError(422, "invalid_model_id", "model_id必须为M0、M1、M2、M3、M4或M5")
        return envelope(app.state.results.model_confusion, model_id, source="回顾性保留集混淆矩阵")

    @app.get("/api/v1/models/errors", response_model=APIEnvelope)
    async def model_errors() -> dict[str, Any]:
        return envelope(app.state.results.model_error_analysis, source="回顾性保留集错误重合汇总")

    @app.get("/api/v1/fusion/summary", response_model=APIEnvelope)
    async def fusion_summary() -> dict[str, Any]:
        return envelope(app.state.results.fusion_summary, source="开发集融合、投票与动态仲裁结果")

    @app.get("/api/v1/predict/example")
    async def prediction_example() -> FileResponse:
        try:
            path = app.state.results.synthetic_example_path()
        except ResultUnavailable as exc:
            raise APIError(404, "example_unavailable", str(exc)) from exc
        return FileResponse(path, media_type="text/csv", filename="synthetic_format_example.csv",
                            headers={"X-Example-Notice": "synthetic-format-only-no-biological-meaning"})

    @app.post("/api/v1/predict")
    def predict(request: Request, file: UploadFile = File(...), model_id: str | None = Form(None), dataset_id: str | None = Form(None)) -> dict[str, Any]:
        filename = file.filename or ""
        if Path(filename).suffix.lower() != ".csv":
            raise APIError(415, "unsupported_file_type", "仅接受CSV文件。")
        try:
            payload = file.file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            file.file.close()
        if len(payload) > MAX_UPLOAD_BYTES:
            raise APIError(413, "file_too_large", "上传文件超过5 MiB限制。")
        if not payload:
            raise APIError(422, "invalid_input", "上传CSV为空文件。")
        if model_id and model_id != 'frozen_m1':
            from .platform2.models import Models
            if not dataset_id:
                raise APIError(422, 'dataset_required', '请选择模型所属数据集')
            try:
                result = Models(app.state.platform_jobs.project).predict(model_id, dataset_id, payload)
            except (ValueError, OSError, UnicodeError) as exc:
                raise APIError(422, 'invalid_input', str(exc)) from exc
            return {'status': 'success', 'data': result}
        if dataset_id and dataset_id != 'pancan':
            raise APIError(422, 'dataset_mismatch', '冻结M1只接受PANCAN RNA-Seq特征，不接受GEO数据')
        try:
            frame = validate_upload(payload)
        except (UploadValidationError, InputValidationError) as exc:
            raise APIError(422, "invalid_input", str(exc)) from exc
        try:
            inference_start = time.perf_counter()
            result = app.state.predictor(frame)
        except (PredictionError, ModelArtifactError) as exc:
            message = str(exc).replace(str(PROJECT_ROOT), "项目目录")
            if any(token in message for token in ("环境版本不匹配", "Python", "找不到模型", "可信摘要", "Pipeline")):
                raise APIError(503, "model_unavailable", message) from exc
            raise APIError(422, "prediction_failed", "输入通过格式检查，但冻结模型推理失败。请查看后端状态与日志。") from exc
        except Exception as exc:
            logger.exception("Prediction bridge failed: %s", type(exc).__name__)
            raise APIError(503, "prediction_unavailable", "冻结模型当前不可用，请检查后端环境状态。") from exc
        result.update(dataset_id='pancan', inference_seconds=time.perf_counter()-inference_start)
        return {"status": "success", "data": result}

    # Keep static historical routes before /experiments/{id} and /models/{id}.
    app.include_router(platform_router)
    return app


app = create_app()
