# -*- coding: utf-8 -*-
"""从已冻结的保留集预测和标签完成报告后处理；绝不拟合或预测模型。"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pandas as pd

from ablation_engine import atomic_json, read_json
from config import CLASS_ORDER, PROJECT_DIR
from final_holdout import (
    MODEL_LABELS, MODEL_ORDER, collect_development_metrics, plot_all,
    sha256, write_reports, write_csv, configure_fonts, _save,
)
import final_holdout as _evaluation_module
import matplotlib.pyplot as plt
import numpy as np


def refresh_score_figures(out: Path, summary: pd.DataFrame, devtest: pd.DataFrame) -> None:
    """从已保存指标重绘两张对照图，图例置于图外，避免遮挡柱形。"""
    configure_fonts()
    order = list(MODEL_ORDER)
    labels = [MODEL_LABELS[m] for m in order]
    x = np.arange(len(order))
    for dev_col, round_col, test_col, ylabel, title, filename in (
        ("development_macro_f1_100fold_mean", "development_macro_f1_20round_oof_mean",
         "macro_f1", "Macro-F1", "开发集与回顾性保留集 Macro-F1",
         "01_开发集与测试集_MacroF1"),
        ("development_balanced_accuracy_100fold_mean", "development_balanced_accuracy_20round_oof_mean",
         "balanced_accuracy", "Balanced Accuracy", "开发集与回顾性保留集 Balanced Accuracy",
         "02_开发集与测试集_BalancedAccuracy"),
    ):
        fig, ax = plt.subplots(figsize=(11, 6.0), layout="constrained")
        width = 0.24
        legend_labels = ["开发集100折均值", "开发集20轮完整OOF均值", "161例保留集"]
        colors = ["#7B8DA6", "#9EB7A6", "#D86F63"]
        handles = []
        indexed = devtest.set_index("model").loc[order]
        for j, (column, color) in enumerate(zip((dev_col, round_col, test_col), colors)):
            values = indexed[column].to_numpy(dtype=float)
            handles.append(ax.bar(x + (j - 1) * width, values, width=width, color=color))
        lowest = min(indexed[dev_col].min(), indexed[round_col].min(), indexed[test_col].min())
        ax.set_ylim(max(0.0, float(lowest) - 0.02), 1.01)
        ax.set_xticks(x, labels, rotation=20, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_title(title + "\n重复交叉验证为开发集描述性结果；保留集为单次回顾性评价")
        ax.grid(axis="y", color="#E6E9ED", linewidth=0.7)
        ax.set_axisbelow(True)
        fig.legend(handles, legend_labels, frameon=False, ncol=3,
                   loc="outside lower center")
        _save(fig, out / "figures", filename)


def write_completion_records(out: Path, audit: dict) -> None:
    atomic_json(out / "status.json", {
        "status": "complete", "completed": datetime.now().isoformat(),
        "test_evaluation_performed": True, "models": list(MODEL_ORDER),
        "no_post_test_model_selection": True,
        "resumed_only_postprocessing_from_frozen_predictions": True,
    })
    atomic_json(PROJECT_DIR / "results" / "latest_final_holdout_evaluation.json", {
        "run_directory": str(out.relative_to(PROJECT_DIR / "results")), "status": "complete"})
    audit["postprocessing_source_sha256"] = sha256(Path(__file__))
    audit["final_outputs"] = {
        str(p.relative_to(out)): sha256(p)
        for p in out.rglob("*") if p.is_file() and p.name != "final_evaluation_audit.json"
    }
    atomic_json(out / "final_evaluation_audit.json", audit)


def finalize() -> Path:
    out = PROJECT_DIR / "results" / "final_holdout_evaluation"
    audit_path = out / "final_evaluation_audit.json"
    audit = read_json(audit_path)
    if audit.get("status") == "complete":
        # 仅从已完成的汇总CSV优化图例排版，不重新读取测试数据或标签。
        summary = pd.read_csv(out / "final_test_summary.csv")
        devtest = pd.read_csv(out / "development_vs_test.csv")
        refresh_score_figures(out, summary, devtest)
        audit["chart_layout_refreshed_from_saved_metrics"] = True
        write_completion_records(out, audit)
        return out
    if audit.get("status") != "all_predictions_frozen_before_test_labels":
        raise RuntimeError("只允许从标签读取前已冻结的预测快照恢复报告")
    configuration = read_json(out / "final_configuration.json")
    manifest = read_json(PROJECT_DIR / "data" / "split_manifest.json")
    prediction_path = out / "checkpoints" / "test_predictions_before_labels.csv"
    if sha256(prediction_path) != audit.get("test_prediction_snapshot_sha256"):
        raise RuntimeError("测试预测快照哈希不匹配，拒绝继续")

    predictions = pd.read_csv(out / "final_test_predictions.csv", dtype={"sample_id": str})
    frozen_predictions = pd.read_csv(prediction_path, dtype={"sample_id": str})
    if len(predictions) != 161 or predictions.sample_id.tolist() != manifest["reserved_test_ids"]:
        raise RuntimeError("已保存的测试预测与固定161个保留样本顺序不一致")
    if frozen_predictions.sample_id.tolist() != predictions.sample_id.tolist():
        raise RuntimeError("标签前冻结的预测与最终表样本顺序不一致")
    for model in MODEL_ORDER:
        if not predictions[f"pred_{model}"].astype(str).equals(
                frozen_predictions[f"pred_{model}"].astype(str)):
            raise RuntimeError(f"{model}最终预测与标签前预测快照不一致")
    if predictions.sample_id.duplicated().any() or predictions.y_true.isna().any():
        raise RuntimeError("预测样本重复或已保存真实标签缺失")
    if not predictions.y_true.astype(str).isin(CLASS_ORDER).all():
        raise RuntimeError("保存的真实类别包含未知标签")

    model_audit = pd.read_csv(out / "final_model_fit_audit.csv")
    if (len(model_audit) != 8 or not model_audit.fit_samples.eq(640).all() or
            not model_audit.reserved_test_fit_samples.eq(0).all() or
            not model_audit.train_test_id_overlap.eq(0).all()):
        raise RuntimeError("拟合审计未确认六方案均仅使用640个开发样本")

    sources = audit["preflight"]["sources"]
    dev_metrics = collect_development_metrics(sources)
    summary = pd.read_csv(out / "final_test_summary.csv")
    # summary 已含开发集指标；去重后用原始CV汇总表作为唯一开发集来源，避免merge列名_x/_y。
    duplicated_development_columns = [
        "development_macro_f1_100fold_mean", "development_macro_f1_20round_oof_mean",
        "development_balanced_accuracy_100fold_mean",
    ]
    devtest = dev_metrics.merge(
        summary.drop(columns=duplicated_development_columns, errors="ignore"),
        on=["model", "model_name"], how="left", validate="one_to_one")
    write_csv(devtest, out / "development_vs_test.csv")

    perclass = pd.read_csv(out / "final_test_per_class_metrics.csv")
    confusion = pd.read_csv(out / "final_confusion_matrices.csv")
    errors = pd.read_csv(out / "final_test_errors.csv")
    overlap_long = pd.read_csv(out / "final_error_overlap.csv")
    overlap = overlap_long.pivot(index="model_a", columns="model_b",
                                 values="shared_error_sample_count").reindex(
                                     index=MODEL_ORDER, columns=MODEL_ORDER)
    error_patterns = pd.read_csv(out / "final_error_patterns.csv")
    changes = pd.read_csv(out / "final_M4_M5_error_changes_vs_M1.csv")
    error_flags = pd.DataFrame({m: predictions[f"pred_{m}"].astype(str).ne(
        predictions.y_true.astype(str)) for m in MODEL_ORDER})
    tables = {
        "summary": summary, "perclass": perclass, "confusion": confusion,
        "errors": errors, "error_overlap": overlap, "error_patterns": error_patterns,
        "error_changes": changes,
        "development_vs_test": devtest,
        "n_samples_with_multiple_model_errors": int(error_flags.sum(axis=1).ge(2).sum()),
    }
    stability_path = (Path(sources["latest_full_feature_ablation.json"]) /
                      "stability" / "stability_summary.csv")
    stability = pd.read_csv(stability_path)
    if not {"variance", "anova", "svc_l2"}.issubset(set(stability.method)) or not (stability.k == 50).any():
        raise RuntimeError("已有开发集30次子采样稳定性表缺少K=50的三种筛选方法")

    write_reports(out, tables, stability, audit["preflight"], configuration)
    # pandas 3 将 tuple 解释为多轴索引；绘图顺序需要显式 list 索引。
    _evaluation_module.MODEL_ORDER = list(MODEL_ORDER)
    plot_all(out, tables)
    refresh_score_figures(out, summary, devtest)
    (out / "结果图表索引.md").write_text(
        "# 最终保留集评价图表索引\n\n" + "\n".join(
            f"- {i:02d}：{name}（PNG 330 DPI、PDF）"
            for i, name in enumerate((
                "开发集与测试集 Macro-F1", "开发集与测试集 Balanced Accuracy",
                "六模型测试集分类性能", "M1 五类别混淆矩阵", "各癌种分类指标",
                "模型错误样本重合", "特征数量与测试集性能"), start=1)) +
        "\n\n所有图均由已保存的真实测试预测及开发集记录生成。\n",
        encoding="utf-8")

    audit.update({
        "status": "complete",
        "model_fit_started": True,
        "all_six_model_fits_completed_before_test_labels": True,
        "test_labels_parsed": True,
        "test_labels_parsed_after_predictions": True,
        "test_samples_scored": 161,
        "test_predictions_written_before_test_labels": True,
        "test_set_fit_samples": 0,
        "test_set_selector_fit_samples": 0,
        "test_set_scaler_fit_samples": 0,
        "test_set_model_selection_or_tuning": False,
        "final_model_selection_changed_after_test": False,
        "postprocessing_resumed_from_frozen_prediction_snapshot": True,
        "postprocessing_performed_no_fit_or_prediction": True,
        "test_prediction_snapshot_sha256_before_labels": audit["test_prediction_snapshot_sha256"],
        "final_outputs": {
            str(p.relative_to(out)): sha256(p)
            for p in out.rglob("*") if p.is_file() and p.name != "final_evaluation_audit.json"
        },
    })
    write_completion_records(out, audit)
    return out


if __name__ == "__main__":
    print(finalize())
