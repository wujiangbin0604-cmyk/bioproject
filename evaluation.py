# -*- coding: utf-8 -*-
"""开发集评价指标和记录汇总；最终测试阶段保留独立受限入口。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (balanced_accuracy_score, classification_report,
                             confusion_matrix, f1_score, make_scorer)

from config import CLASS_ORDER
from data_loader import write_json

SCORING = {
    "macro_f1": make_scorer(f1_score, average="macro", labels=list(CLASS_ORDER), zero_division=0),
    "balanced_accuracy": "balanced_accuracy",
}


def compute_metrics(y_true, y_pred) -> dict[str, float]:
    """Macro-F1 为五类 F1 的等权平均；Balanced Accuracy 为各类召回率平均。"""
    return {
        "macro_f1": float(f1_score(y_true, y_pred, average="macro",
                                  labels=list(CLASS_ORDER), zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
    }


def summarize_cv(details: pd.DataFrame) -> pd.DataFrame:
    """分数均值和样本标准差 ddof=1 仅作描述统计，不当作独立重复的推断。"""
    summary = {key: details.iloc[0][key] for key in
               ("model_id", "selection_method", "k", "C", "cv_mode")}
    summary["n_evaluations"] = len(details)
    for metric in ("macro_f1", "balanced_accuracy"):
        for subset in ("train", "validation"):
            values = details[f"{subset}_{metric}"].to_numpy(dtype=float)
            summary[f"{subset}_{metric}_mean"] = float(np.mean(values))
            summary[f"{subset}_{metric}_std"] = float(np.std(values, ddof=1))
        summary[f"gap_{metric}_mean"] = float(details[f"gap_{metric}"].mean())
        summary[f"gap_{metric}_std"] = float(details[f"gap_{metric}"].std(ddof=1))
    summary["fit_seconds_mean"] = float(details["fit_seconds"].mean())
    return pd.DataFrame([summary])


def save_development_oof_report(predictions: pd.DataFrame, output: Path) -> None:
    """只汇总一次标准五折的开发集折外预测；不称为独立测试性能。"""
    if predictions["sample_id"].duplicated().any():
        raise ValueError("OOF 汇总只接受每个开发样本恰好一次预测；重复CV需按重复轮次分别处理")
    report = classification_report(predictions["y_true"], predictions["y_pred"],
                                   labels=list(CLASS_ORDER), output_dict=True, zero_division=0)
    write_json(output / "development_oof_metrics.json",
               {"scope": "development_out_of_fold", **compute_metrics(predictions.y_true, predictions.y_pred)})
    pd.DataFrame(report).T.to_csv(output / "development_oof_classification_report.csv",
                                encoding="utf-8-sig")
    matrix = confusion_matrix(predictions.y_true, predictions.y_pred, labels=list(CLASS_ORDER))
    pd.DataFrame(matrix, index=pd.Index(CLASS_ORDER, name="true_label"), columns=CLASS_ORDER).to_csv(
        output / "development_oof_confusion_matrix.csv", encoding="utf-8-sig")


def evaluate_final_test(*args, **kwargs):
    """后续应在最终配置被冻结后才实现并显式调用。"""
    raise NotImplementedError("第一阶段不执行最终测试；分类报告和混淆矩阵的最终测试版本留待第五阶段")


if __name__ == "__main__":
    print("指标：Macro-F1、Balanced Accuracy、训练减验证的性能差距；标准差采用 ddof=1。")
