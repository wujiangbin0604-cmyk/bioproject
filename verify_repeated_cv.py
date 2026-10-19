# -*- coding: utf-8 -*-
"""独立复算重复CV产物；不拟合模型、不加载保留测试表达或标签。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import RepeatedStratifiedKFold

from config import CLASS_ORDER, ExperimentConfig
from data_loader import write_json
from evaluation import compute_metrics


def verify(output: Path) -> dict:
    """从逐样本预测复算每折/每轮分数、错误率、混淆矩阵，并重建100折ID。"""
    read = lambda name: json.loads((output / name).read_text(encoding="utf-8"))
    checks = []

    def check(name: str, condition) -> None:
        if not bool(condition):
            raise AssertionError(f"验收失败：{name}")
        checks.append(name)

    def close(name: str, a, b) -> None:
        check(name, np.allclose(a, b, rtol=1e-11, atol=1e-12))

    required = ("repeated_cv_fold_results.csv", "repeated_cv_round_summary.csv", "repeated_cv_summary.json",
                "repeated_cv_oof_predictions.csv", "sample_prediction_stability.csv",
                "repeated_cv_confusion_matrix.csv", "repeated_cv_performance.png", "repeated_cv_fit_audit.csv")
    for name in required:
        check(f"必需文件存在：{name}", (output / name).is_file())
    status, summary, manifest = read("stage_status.json"), read("repeated_cv_summary.json"), read("split_manifest.json")
    config, frozen, progress = read("config.json"), read("frozen_pipeline.json"), read("cv_progress.json")
    folds = read("cv_fold_indices.json")["folds"]
    details = pd.read_csv(output / "repeated_cv_fold_results.csv")
    rounds = pd.read_csv(output / "repeated_cv_round_summary.csv")
    oof = pd.read_csv(output / "repeated_cv_oof_predictions.csv")
    train_predictions = pd.read_csv(output / "training_predictions.csv")
    samples = pd.read_csv(output / "sample_prediction_stability.csv").set_index("sample_id")
    audit = pd.read_csv(output / "repeated_cv_fit_audit.csv")
    cm = pd.read_csv(output / "repeated_cv_confusion_matrix.csv")
    dev_ids, reserved_ids = manifest["development_ids"], set(manifest["reserved_test_ids"])
    labels = oof.loc[oof["round"].eq(1)].set_index("sample_id").y_true.loc[dev_ids]
    dev_set = set(dev_ids)
    check("640个开发ID、161个保留ID，互斥", len(dev_set) == 640 and len(reserved_ids) == 161 and not dev_set & reserved_ids)
    check("正好100折、20轮、12800个验证预测、51200个训练预测",
          (len(details), len(rounds), len(oof), len(train_predictions), len(audit), len(folds)) == (100, 20, 12800, 51200, 100, 100))
    check("完成状态与进度", status["status"] == "complete" and progress["completed_evaluations"] == 100)
    check("没有特征选择、调参或保留测试评估", all(status[k] is False for k in (
        "feature_selection_performed", "hyperparameter_search_performed", "test_evaluation_performed", "stages_2_3_4_5_6_started")))
    check("固定C、全部20531个基因", details.C.eq(1).all() and details.n_features_input.eq(20531).all()
          and details.n_features_model.eq(20531).all() and details.selection_method.eq("none").all())
    check("流水线只有StandardScaler及LinearSVC", [x[0] for x in frozen["pipeline_steps"]] == ["scale", "model"])
    model_params = frozen["pipeline_steps"][1][1]["parameters"]
    check("模型完整固定参数", model_params["C"] == 1 and model_params["dual"] == "auto"
          and model_params["random_state"] == 42 and model_params["max_iter"] == 50000)
    check("开发值和保留标签隔离记录", read("development_data_record.json")["reserved_values_analyzed"] is False
          and read("development_data_record.json")["reserved_labels_analyzed"] is False)
    splitter = RepeatedStratifiedKFold(n_splits=5, n_repeats=20, random_state=42)
    sample_array = np.asarray(dev_ids)
    for evaluation_id, ((train, valid), saved) in enumerate(zip(splitter.split(sample_array, labels), folds), 1):
        round_id, fold_id = (evaluation_id - 1) // 5 + 1, (evaluation_id - 1) % 5 + 1
        train_ids, valid_ids = sample_array[train].tolist(), sample_array[valid].tolist()
        check(f"折{evaluation_id}：重建划分与原记录完全一致",
              saved["train_sample_ids"] == train_ids and saved["validation_sample_ids"] == valid_ids)
        check(f"折{evaluation_id}：512/128，训练验证和保留ID隔离",
              len(train_ids) == 512 and len(valid_ids) == 128 and not set(train_ids) & set(valid_ids)
              and not (set(train_ids) | set(valid_ids)) & reserved_ids)
        pred = oof.loc[oof.evaluation_id.eq(evaluation_id)].set_index("sample_id")
        tr = train_predictions.loc[train_predictions.evaluation_id.eq(evaluation_id)].set_index("sample_id")
        check(f"折{evaluation_id}：训练和验证预测ID准确", pred.index.tolist() == valid_ids and tr.index.tolist() == train_ids)
        check(f"折{evaluation_id}：记录轮次和折号准确", pred["round"].eq(round_id).all() and pred.fold.eq(fold_id).all())
        check(f"折{evaluation_id}：真实标签一致", pred.y_true.equals(labels.loc[valid_ids])
              and tr.y_true.equals(labels.loc[train_ids]))
        row = details.loc[details.evaluation_id.eq(evaluation_id)].iloc[0]
        train_scores, val_scores = compute_metrics(tr.y_true, tr.y_pred), compute_metrics(pred.y_true, pred.y_pred)
        for metric in train_scores:
            close(f"折{evaluation_id}：复算训练{metric}", row[f"train_{metric}"], train_scores[metric])
            close(f"折{evaluation_id}：复算验证{metric}", row[f"validation_{metric}"], val_scores[metric])
            close(f"折{evaluation_id}：复算差距{metric}", row[f"gap_{metric}"], train_scores[metric] - val_scores[metric])
    check("全体验证预测仅来自开发样本", set(oof.sample_id) == dev_set and not set(oof.sample_id) & reserved_ids)
    check("每个开发样本正好20个验证预测", oof.groupby("sample_id").size().eq(20).all())
    check("每轮同一开发样本只出现一次", not oof.duplicated(["round", "sample_id"]).any())
    close("is_error逐项一致", oof.is_error.astype(int), oof.y_true.ne(oof.y_pred).astype(int))
    for round_id, pred in oof.groupby("round"):
        row = rounds.loc[rounds["round"].eq(round_id)].iloc[0]
        check(f"轮{round_id}：640个OOF且覆盖开发ID", len(pred) == 640 and set(pred.sample_id) == dev_set)
        for metric, value in compute_metrics(pred.y_true, pred.y_pred).items():
            close(f"轮{round_id}：合并OOF复算{metric}", row[f"oof_{metric}"], value)
        fold_rows = details.loc[details["round"].eq(round_id)]
        for metric in ("train_macro_f1", "validation_macro_f1", "train_balanced_accuracy",
                       "validation_balanced_accuracy", "gap_macro_f1", "gap_balanced_accuracy", "fit_seconds", "predict_seconds"):
            values = fold_rows[metric]
            expected = {"mean": values.mean(), "std": values.std(ddof=1), "min": values.min(), "max": values.max(),
                        "p05": values.quantile(.05), "p25": values.quantile(.25), "median": values.median(),
                        "p75": values.quantile(.75), "p95": values.quantile(.95)}
            for stat, value in expected.items():
                close(f"轮{round_id}：{metric}_{stat}", row[f"{metric}_{stat}"], value)
        expected_cm = confusion_matrix(pred.y_true, pred.y_pred, labels=list(CLASS_ORDER))
        long_cm = cm.loc[cm["round"].eq(round_id)].pivot(index="true_label", columns="predicted_label", values="count")
        saved_cm = pd.read_csv(output / "round_confusion_matrices" / f"round_{round_id:02d}_confusion_matrix.csv", index_col=0)
        close(f"轮{round_id}：混淆矩阵长表一致", long_cm.loc[list(CLASS_ORDER), list(CLASS_ORDER)], expected_cm)
        close(f"轮{round_id}：单轮矩阵一致", saved_cm.loc[list(CLASS_ORDER), list(CLASS_ORDER)], expected_cm)
        saved_oof = pd.read_csv(output / "round_oof" / f"round_{round_id:02d}_oof_predictions.csv").set_index("sample_id")
        check(f"轮{round_id}：单独OOF文件一致", saved_oof.index.tolist() == dev_ids and
              saved_oof[["y_true", "y_pred"]].equals(pred.set_index("sample_id").loc[dev_ids, ["y_true", "y_pred"]]))
    expected_errors = oof.groupby("sample_id").is_error.sum().loc[samples.index]
    close("每个样本错误次数重算", samples.error_count, expected_errors)
    close("每个样本错误比例重算", samples.error_rate, expected_errors / 20)
    close("每个样本预测类别次数之和", samples[[f"predicted_{c}_count" for c in CLASS_ORDER]].sum(axis=1), np.repeat(20, 640))
    check("总错误及错误样本数与JSON一致", summary["total_oof_error_count"] == int(expected_errors.sum()) and
          summary["n_samples_with_any_error"] == int(expected_errors.gt(0).sum()))
    check("满分折/无错轮数重算", summary["n_perfect_validation_folds"] == int(details.validation_macro_f1.eq(1).sum())
          and summary["n_perfect_oof_rounds"] == int(rounds.oof_error_count.eq(0).sum()))
    pooled = cm.loc[cm["round"].eq(0)].pivot(index="true_label", columns="predicted_label", values="count")
    close("汇总12800个重复OOF的混淆矩阵", pooled.loc[list(CLASS_ORDER), list(CLASS_ORDER)],
          confusion_matrix(oof.y_true, oof.y_pred, labels=list(CLASS_ORDER)))
    for metric, stats in summary["fold_descriptive_statistics"].items():
        close(f"JSON整体{metric}均值", stats["mean"], details[metric].mean())
        close(f"JSON整体{metric}标准差", stats["std"], details[metric].std(ddof=1))
        for stat, quantile in (("min", 0), ("p05", .05), ("p25", .25), ("median", .5), ("p75", .75), ("p95", .95), ("max", 1)):
            close(f"JSON整体{metric}分位{stat}", stats[stat], details[metric].quantile(quantile))
    check("100折拟合前未拟合、特征和C一致", audit.pipeline_unfitted_before_fold.all() and
          audit.scaler_training_samples.eq(512).all() and audit.scaler_features.eq(20531).all()
          and audit.model_features_in.eq(20531).all() and audit.model_C.eq(1).all())
    check("100折审计无交集，标准化器拟合核验通过", audit.train_validation_overlap.eq(0).all()
          and audit.reserved_test_overlap.eq(0).all() and audit.scaler_fit_audit_passed.all())
    check("100折标准化均值和方差误差在数值容差内", audit.scaler_mean_max_abs_error.max() < 1e-10
          and audit.scaler_variance_max_abs_error.max() < 1e-9)
    check("无收敛警告", not any(w["category"] == "ConvergenceWarning" for w in read("warnings.json")["warnings"]))
    check("未进行独立样本推断或计算置信区间", summary["statistical_conventions"]["inferential_tests_performed"] is False
          and summary["statistical_conventions"]["confidence_intervals_computed"] is False)
    if not config["label_permutation_enabled"]:
        check("本次标签置乱关闭", read("label_permutation.json")["enabled"] is False
              and not (output / "development_label_permutation.csv").exists())
        comparison = summary["first_round_comparison"]
        check("首轮划分及预测重现原五折", comparison["first_round_same_split_as_original_five_fold"]
              and comparison["first_round_same_predictions"])
    else:
        shuffled = pd.read_csv(output / "development_label_permutation.csv").set_index("sample_id").loc[dev_ids]
        expected = np.random.default_rng(config["permutation_seed"]).permutation(shuffled.original_label.to_numpy())
        check("置乱由已记录种子复现且仅含开发ID", set(shuffled.index) == dev_set and
              np.array_equal(expected, shuffled.permuted_label.to_numpy()))
    with Image.open(output / "repeated_cv_performance.png") as img:
        img.verify()
    with Image.open(output / "repeated_cv_performance.png") as img:
        check("PNG完整且DPI至少300", min(img.info.get("dpi", (0, 0))) >= 300 and min(img.size) > 1000)
    check("PDF矢量版本存在", (output / "repeated_cv_performance.pdf").read_bytes().startswith(b"%PDF"))
    for name, digest in read("source_sha256.json").items():
        check(f"运行代码快照指纹：{name}", hashlib.sha256((output / "source_snapshot" / name).read_bytes()).hexdigest() == digest)
    report = {"passed": True, "n_checks": len(checks), "checks": checks, "model_refits_performed": 0,
              "reserved_test_values_or_labels_loaded": False, "run_directory": str(output)}
    write_json(output / "verification.json", report)
    print(f"验收通过：{len(checks)}项，未重新拟合，未加载保留测试数据。")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--permutation", action="store_true", help="核验最近标签置乱运行，而不执行置乱实验")
    args = parser.parse_args()
    cfg = ExperimentConfig()
    if args.run_dir:
        directory = args.run_dir.resolve()
    else:
        pointer = "latest_repeated_permutation.json" if args.permutation else "latest_repeated_cv.json"
        latest = json.loads((cfg.output_dir / pointer).read_text(encoding="utf-8"))
        directory = cfg.output_dir / latest["run_directory"]
    verify(directory)
