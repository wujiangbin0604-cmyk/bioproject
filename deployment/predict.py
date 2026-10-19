# -*- coding: utf-8 -*-
"""M1 ANOVA Top50 + LinearSVC单样本研究型预测CLI/API。"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any

import pandas as pd

try:  # 支持 `python -m deployment.predict` 和 `python deployment/predict.py`
    from .input_validator import InputData, validate_single_sample
    from .model_loader import DEFAULT_MODEL_PATH, ModelArtifactError, load_deployment_model
except ImportError:  # pragma: no cover - 直接脚本调用路径
    from input_validator import InputData, validate_single_sample
    from model_loader import DEFAULT_MODEL_PATH, ModelArtifactError, load_deployment_model

logger = logging.getLogger("gene_expression_predict")


class PredictionError(RuntimeError):
    """模型推理阶段异常。"""


def predict_single_sample(input_data: InputData,
                          model_path: str | Path | None = None) -> dict[str, Any]:
    """对一个具备完整命名基因列的样本预测癌种类别，不输出或暗示概率。

    `input_data` 可为CSV路径或pandas DataFrame。输入列顺序可以不同，但名称必须与
    训练时保存的20,531个 `gene_*` 特征完全一致。
    """
    try:
        loaded = load_deployment_model(model_path)
        validated = validate_single_sample(input_data, loaded.feature_names)
        predicted = str(loaded.pipeline.predict(validated.features)[0])
    except (ModelArtifactError, ValueError) as exc:
        if isinstance(exc, PredictionError):
            raise
        raise PredictionError(str(exc)) from exc
    except Exception as exc:
        raise PredictionError(f"模型推理失败：{type(exc).__name__}: {exc}") from exc

    if predicted not in loaded.metadata["classifier_class_order"]:
        raise PredictionError(f"模型返回了未知类别：{predicted}")
    return {
        "sample_id": validated.sample_id,
        "predicted_class": predicted,
        "model_name": loaded.metadata["model_name"],
        "model_version": loaded.metadata["model_version"],
        "input_feature_count": validated.input_feature_count,
        "selected_feature_count": len(loaded.selected_gene_names),
        "input_columns_reordered": validated.input_columns_reordered,
        "inference_status": "success",
        "probability_output": False,
        "interpretation_notice": (
            "仅输出五类肿瘤表达类别预测，不是校准概率、患癌风险、临床诊断或早筛结果。"),
    }


def _write_json(result: dict[str, Any], output: str | Path) -> Path:
    path = Path(output).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    except (OSError, TypeError, ValueError) as exc:
        raise PredictionError(f"无法保存JSON输出：{exc}") from exc
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对一条与UCI RNA-Seq Dataset 401格式兼容的五癌种表达记录进行研究型分类。")
    parser.add_argument("--input", required=True, help="恰好一行、含sample_id(可选)和20531个gene_*列的CSV")
    parser.add_argument("--model", default=None, help=f"可选模型路径（默认：{DEFAULT_MODEL_PATH}；仅接受固定可信SHA-256工件）")
    parser.add_argument("--output", default=None, help="可选JSON输出路径")
    parser.add_argument("--verbose", action="store_true", help="打印输入检查、模型版本和列重排摘要")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = predict_single_sample(args.input, args.model)
        if args.verbose:
            logger.info("模型版本：%s", result["model_version"])
            logger.info("输入特征数：%d；模型使用特征数：%d；按名称恢复列序：%s",
                        result["input_feature_count"], result["selected_feature_count"],
                        "是" if result["input_columns_reordered"] else "否")
        print(f"样本ID：{result['sample_id'] or '未提供'}")
        print(f"模型：{result['model_name']}")
        print(f"模型版本：{result['model_version']}")
        print(f"预测类别：{result['predicted_class']}")
        print(f"输入特征数量：{result['input_feature_count']}")
        print(f"模型使用特征数量：{result['selected_feature_count']}")
        print("推理状态：推理完成")
        if args.output:
            saved = _write_json(result, args.output)
            print(f"JSON结果：{saved}")
        return 0
    except (PredictionError, ModelArtifactError) as exc:
        print(f"预测失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
