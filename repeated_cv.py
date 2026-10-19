# -*- coding: utf-8 -*-
"""阶段一扩展：固定全特征 SVM 的重复CV及可选开发集标签置乱负对照。"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from baseline import build_baseline
from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from cross_validation import evaluate_fixed_pipeline, frozen_pipeline_record
from data_loader import DevelopmentData, load_existing_development_data, write_json
from evaluation import compute_metrics
from visualization import plot_repeated_cv


def descriptive(values) -> dict:
    """仅作描述：样本标准差ddof=1、线性插值分位数，不计算独立样本推断。"""
    x = np.asarray(values, dtype=float)
    if x.size == 0 or not np.isfinite(x).all():
        raise ValueError("描述统计输入为空或包含非有限值")
    return {"n": int(x.size), "mean": float(x.mean()),
            "std": float(x.std(ddof=1)) if x.size > 1 else 0.0,
            "min": float(x.min()), "p05": float(np.quantile(x, .05)),
            "p25": float(np.quantile(x, .25)), "median": float(np.median(x)),
            "p75": float(np.quantile(x, .75)), "p95": float(np.quantile(x, .95)),
            "max": float(x.max())}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parent_baseline(cfg: ExperimentConfig) -> tuple[Path, dict]:
    """锁定原基线参数和样本名单，防止借扩展实验更换数据或配置。"""
    pointer = _read_json(cfg.output_dir / "latest_stage1.json")
    parent = cfg.output_dir / pointer["run_directory"]
    status = _read_json(parent / "stage_status.json")
    if pointer["status"] != "complete" or status["stage_1"] != "complete":
        raise ValueError("原五折基线未成功完成")
    original = _read_json(parent / "config.json")
    for key in ("random_state", "test_size", "n_splits", "n_repeats", "baseline_c",
                "max_iter", "tolerance", "class_weight", "numeric_threads",
                "expected_samples", "expected_features"):
        if cfg.to_dict()[key] != original[key]:
            raise ValueError(f"扩展实验参数 {key} 与原基线不同")
    if _read_json(cfg.split_manifest_path) != _read_json(parent / "split_manifest.json"):
        raise ValueError("当前划分清单与原五折基线不一致")
    return parent, original


def permute_development_labels(development: DevelopmentData, seed: int,
                               output: Path) -> DevelopmentData:
    """只置乱640个开发标签；不读取保留测试标签，不置乱基因表达或样本ID。"""
    shuffled = pd.Series(np.random.default_rng(seed).permutation(development.y.to_numpy()),
                         index=development.y.index, name=development.y.name)
    pd.DataFrame({"sample_id": development.y.index, "original_label": development.y.to_numpy(),
                  "permuted_label": shuffled.to_numpy()}).to_csv(
                      output / "development_label_permutation.csv", index=False, encoding="utf-8-sig")
    if not shuffled.value_counts().sort_index().equals(development.y.value_counts().sort_index()):
        raise AssertionError("置乱改变了开发集类别计数")
    write_json(output / "label_permutation.json", {
        "enabled": True, "seed": seed, "generator": "numpy.random.default_rng",
        "scope": "fixed_640_development_labels_only", "reserved_labels_accessed": False,
        "n_labels": len(shuffled), "n_labels_changed": int(shuffled.ne(development.y).sum()),
        "method": "一次全局开发标签置乱后固定，按置乱标签进行重复分层CV；不是每折单独置乱",
        "interpretation": "单次置乱的诊断性负对照，不是正式置换检验或置换p值",
    })
    return DevelopmentData(development.X, shuffled, development.reserved_test_ids,
                           development.fingerprint, development.split_manifest_path)


def _write_tables(results: dict, development: DevelopmentData, cfg: ExperimentConfig,
                  output: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """汇总100折、20轮、640个样本；每轮OOF先合并640条再评分。"""
    details = results["details"].rename(columns={"repeat": "round"}).copy()
    oof = results["predictions"].rename(columns={"repeat": "round"}).copy()
    oof["is_error"] = oof.y_true.ne(oof.y_pred)
    if len(details) != 100 or len(oof) != 12800:
        raise AssertionError("未完成100折或12800条验证预测")
    details.to_csv(output / "repeated_cv_fold_results.csv", index=False, encoding="utf-8-sig")
    oof.to_csv(output / "repeated_cv_oof_predictions.csv", index=False, encoding="utf-8-sig")
    results["audit"].rename(columns={"repeat": "round"}).to_csv(
        output / "repeated_cv_fit_audit.csv", index=False, encoding="utf-8-sig")
    round_dir, matrix_dir = output / "round_oof", output / "round_confusion_matrices"
    round_dir.mkdir()
    matrix_dir.mkdir()
    round_rows, matrix_rows = [], []
    metric_columns = [c for c in details if c.startswith(("train_", "validation_", "gap_"))
                      and c not in ("train_sample_ids", "validation_sample_ids")]
    metric_columns += ["fit_seconds", "predict_seconds"]
    for round_id, predictions in oof.groupby("round", sort=True):
        if len(predictions) != 640 or predictions.sample_id.nunique() != 640:
            raise AssertionError("某轮OOF未覆盖640个开发样本各一次")
        fold_rows = details.loc[details["round"].eq(round_id)]
        scores = compute_metrics(predictions.y_true, predictions.y_pred)
        row = {"round": int(round_id), "n_folds": len(fold_rows), "n_oof_samples": len(predictions),
               "oof_macro_f1": scores["macro_f1"],
               "oof_balanced_accuracy": scores["balanced_accuracy"],
               "oof_error_count": int(predictions.is_error.sum()),
               "fit_seconds_sum": float(fold_rows.fit_seconds.sum())}
        for column in metric_columns:
            row.update({f"{column}_{stat}": value for stat, value in descriptive(fold_rows[column]).items()})
        round_rows.append(row)
        # 按原开发集顺序保存，便于逐轮对照同一样本；不重新排序标签。
        predictions.set_index("sample_id").loc[development.X.index].reset_index().to_csv(
            round_dir / f"round_{round_id:02d}_oof_predictions.csv", index=False, encoding="utf-8-sig")
        matrix = confusion_matrix(predictions.y_true, predictions.y_pred, labels=list(CLASS_ORDER))
        pd.DataFrame(matrix, index=pd.Index(CLASS_ORDER, name="true_label"), columns=CLASS_ORDER).to_csv(
            matrix_dir / f"round_{round_id:02d}_confusion_matrix.csv", encoding="utf-8-sig")
        for i, true in enumerate(CLASS_ORDER):
            for j, pred in enumerate(CLASS_ORDER):
                matrix_rows.append({"scope": "round", "round": int(round_id),
                                    "true_label": true, "predicted_label": pred, "count": int(matrix[i, j])})
    pooled = confusion_matrix(oof.y_true, oof.y_pred, labels=list(CLASS_ORDER))
    for i, true in enumerate(CLASS_ORDER):
        for j, pred in enumerate(CLASS_ORDER):
            matrix_rows.append({"scope": "pooled_repeated_predictions", "round": 0,
                                "true_label": true, "predicted_label": pred, "count": int(pooled[i, j])})
    pd.DataFrame(matrix_rows).to_csv(output / "repeated_cv_confusion_matrix.csv", index=False, encoding="utf-8-sig")
    rounds = pd.DataFrame(round_rows)
    rounds.to_csv(output / "repeated_cv_round_summary.csv", index=False, encoding="utf-8-sig")
    sample_rows = []
    for sid, predictions in oof.groupby("sample_id", sort=False):
        if len(predictions) != 20 or predictions.y_true.nunique() != 1:
            raise AssertionError("样本未恰好获得20次OOF预测或真实标签不一致")
        counts = predictions.y_pred.value_counts().reindex(CLASS_ORDER, fill_value=0)
        sample_rows.append({"sample_id": sid, "true_label": predictions.y_true.iloc[0],
                            "n_predictions": len(predictions), "correct_count": int((~predictions.is_error).sum()),
                            "error_count": int(predictions.is_error.sum()), "error_rate": float(predictions.is_error.mean()),
                            "modal_prediction": counts.idxmax(), "modal_prediction_count": int(counts.max()),
                            "error_rounds": ";".join(map(str, predictions.loc[predictions.is_error, "round"])),
                            **{f"predicted_{c}_count": int(counts[c]) for c in CLASS_ORDER}})
    samples = pd.DataFrame(sample_rows).set_index("sample_id").loc[development.X.index].reset_index()
    samples.to_csv(output / "sample_prediction_stability.csv", index=False, encoding="utf-8-sig")
    return details, rounds, samples


def _first_round_comparison(results: dict, parent: Path, enabled: bool) -> dict:
    """同随机种子下首轮可与原5折相同，必须披露，不能称为全新重复证据。"""
    if enabled:
        return {"applicable": False, "reason": "标签已置乱，分层划分与真实标签基线无直接对应"}
    original_folds = _read_json(parent / "cv_fold_indices.json")["folds"]
    first = results["folds"][:5]
    matches = all(a["train_sample_ids"] == b["train_sample_ids"] and
                  a["validation_sample_ids"] == b["validation_sample_ids"]
                  for a, b in zip(original_folds, first))
    original = pd.read_csv(parent / "development_oof_predictions.csv")
    current = results["predictions"].loc[lambda x: x["repeat"].eq(1)]
    a = original.set_index("sample_id").sort_index()
    b = current.set_index("sample_id").sort_index()
    same_predictions = a[["y_true", "y_pred"]].equals(b[["y_true", "y_pred"]])
    return {"applicable": True, "first_round_same_split_as_original_five_fold": matches,
            "first_round_same_predictions": same_predictions,
            "note": "若首轮划分相同，新增划分证据来自其余19轮；各轮仍共享同一开发样本集合"}


def run_repeated_experiment(cfg: ExperimentConfig, permute_labels: bool = False,
                            permutation_seed: int = 42) -> Path:
    """仅运行固定C的5×20；不调用特征实验、GridSearchCV或保留测试评分。"""
    if (cfg.cv_mode, cfg.n_splits, cfg.n_repeats, cfg.random_state, cfg.baseline_c) != ("repeated", 5, 20, 42, 1.0):
        raise ValueError("此扩展实验固定 repeated / 5折×20次 / random_state=42 / C=1.0")
    parent, _ = _parent_baseline(cfg)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    group = "stage1_repeated_cv_label_permutation" if permute_labels else "stage1_repeated_cv"
    output = cfg.output_dir / group / stamp
    output.mkdir(parents=True, exist_ok=False)
    from main import environment_record
    write_json(output / "config.json", {**cfg.to_dict(), "label_permutation_enabled": permute_labels,
                                        "permutation_seed": permutation_seed if permute_labels else None,
                                        "parent_baseline_directory": str(parent.relative_to(cfg.output_dir))})
    write_json(output / "environment.json", environment_record())
    # 保存本次实际代码，日后编辑项目不会丢失此次运行的实现及指纹。
    source_dir = output / "source_snapshot"
    source_dir.mkdir()
    source_hashes = {}
    for file in PROJECT_DIR.glob("*.py"):
        content = file.read_bytes()
        (source_dir / file.name).write_bytes(content)
        source_hashes[file.name] = hashlib.sha256(content).hexdigest()
    write_json(output / "source_sha256.json", source_hashes)
    status = {"experiment": group, "status": "running", "n_cv_evaluations_completed": 0,
              "feature_selection_performed": False, "hyperparameter_search_performed": False,
              "test_evaluation_performed": False, "label_permutation_enabled": permute_labels,
              "stages_2_3_4_5_6_started": False}
    write_json(output / "stage_status.json", status)
    start = time.perf_counter()
    try:
        development = load_existing_development_data(cfg, output)
        prior = pd.read_csv(parent / "development_oof_predictions.csv").set_index("sample_id")
        if not np.array_equal(prior.loc[development.y.index, "y_true"].to_numpy(), development.y.to_numpy()):
            raise ValueError("开发集真实标签与原基线记录不同")
        if permute_labels:
            development = permute_development_labels(development, permutation_seed, output)
        else:
            write_json(output / "label_permutation.json", {"enabled": False, "seed": None, "not_run": True})
        estimator = build_baseline(cfg)
        frozen = frozen_pipeline_record(estimator, "full_linear_svm", "none", "all")
        write_json(output / "frozen_pipeline.json", frozen)
        print(f"固定开发集 {development.X.shape}，排除161个保留样本；C=1.0，无特征选择。", flush=True)
        print(f"重复CV 5×20=100次；标签置乱负对照={'开启' if permute_labels else '关闭'}。", flush=True)
        results = evaluate_fixed_pipeline(estimator, development, cfg, output,
                                          frozen_configuration=frozen, checkpoint_every=5,
                                          record_training_predictions=True)
        details, rounds, samples = _write_tables(results, development, cfg, output)
        fold_columns = [c for c in details if c.startswith(("train_", "validation_", "gap_"))]
        fold_columns += ["fit_seconds", "predict_seconds"]
        summary = {
            "experiment": group, "data": {"original_n_samples": 801, "development_n_samples": 640,
                                             "reserved_n_samples_excluded": 161, "n_gene_features": 20531},
            "cv": {"splitter": "RepeatedStratifiedKFold", "n_splits": 5, "n_repeats": 20,
                   "random_state": 42, "n_evaluations": 100, "n_training_per_fold": 512,
                   "n_validation_per_fold": 128},
            "frozen_pipeline": frozen, "feature_selection_performed": False,
            "hyperparameter_search_performed": False, "test_evaluation_performed": False,
            "label_permutation_enabled": permute_labels,
            "permutation_seed": permutation_seed if permute_labels else None,
            "fold_descriptive_statistics": {c: descriptive(details[c]) for c in fold_columns},
            "round_oof_descriptive_statistics": {c: descriptive(rounds[c]) for c in
                                                   ("oof_macro_f1", "oof_balanced_accuracy", "oof_error_count", "fit_seconds_sum")},
            "sample_error_count_descriptive_statistics": descriptive(samples.error_count),
            "sample_error_rate_descriptive_statistics": descriptive(samples.error_rate),
            "n_perfect_validation_folds": int(details.validation_macro_f1.eq(1).sum()),
            "n_perfect_oof_rounds": int(rounds.oof_error_count.eq(0).sum()),
            "n_repeated_oof_predictions": 12800, "total_oof_error_count": int(samples.error_count.sum()),
            "n_samples_with_any_error": int(samples.error_count.gt(0).sum()),
            "n_samples_always_correct": int(samples.error_count.eq(0).sum()),
            "all_fold_audits_passed": bool(results["audit"].scaler_fit_audit_passed.all()),
            "first_round_comparison": _first_round_comparison(results, parent, permute_labels),
            "statistical_conventions": {"std_ddof": 1, "quantiles": [0.05, 0.25, 0.5, 0.75, 0.95],
                                        "quantile_interpolation": "linear", "inferential_tests_performed": False,
                                        "confidence_intervals_computed": False},
            "interpretation": [
                "100个折分数和20个每轮OOF分数共享样本、训练集重叠，属于相关描述性结果。",
                "12800条OOF预测来自640个样本各20次，不能视作12800个独立患者。",
                "仅评估固定全特征C=1模型对内部划分的稳定性，不估计特征选择稳定性。",
                "不能据此证明外部队列泛化；161个保留样本未参与此次拟合或评分。",
                "此前全数据EDA接触过保留样本，该161例也不能被称为未接触的外部队列。",
                "单次标签置乱负对照默认关闭；即使运行也不等于正式置换显著性检验。"],
            "sum_model_fit_seconds": float(details.fit_seconds.sum()),
            "elapsed_seconds_before_plot": time.perf_counter() - start,
        }
        write_json(output / "repeated_cv_summary.json", summary)
        plot_repeated_cv(details, rounds, samples, output, permuted=permute_labels)
        m = summary["fold_descriptive_statistics"]["validation_macro_f1"]
        b = summary["fold_descriptive_statistics"]["validation_balanced_accuracy"]
        text = ["# 阶段一扩展：全特征 Linear SVM 重复交叉验证", "",
                f"标签置乱负对照：{'开启' if permute_labels else '未运行'}。固定640个开发样本、20,531个原始基因；排除161个保留测试样本。",
                "StandardScaler → LinearSVC(C=1.0, dual='auto')；5折×20轮、种子42。每折512训练/128验证，重新克隆并拟合Pipeline。", "",
                f"100折验证Macro-F1：{m['mean']:.8f} ± {m['std']:.8f}，最小{m['min']:.8f}，最大{m['max']:.8f}。",
                f"100折验证Balanced Accuracy：{b['mean']:.8f} ± {b['std']:.8f}，最小{b['min']:.8f}，最大{b['max']:.8f}。",
                f"Macro-F1=1.0：{summary['n_perfect_validation_folds']}/100折；全轮OOF无误：{summary['n_perfect_oof_rounds']}/20轮。",
                f"12,800条重复OOF预测中错误{summary['total_oof_error_count']}次；至少错误一次的开发样本{summary['n_samples_with_any_error']}/640。", "",
                "repeated_cv_round_summary.csv同时保存每轮5折分数的描述统计及合并640条OOF后的指标，两者定义不同。",
                "repeated_cv_confusion_matrix.csv按长表保存20轮混淆矩阵和汇总矩阵（round=0）；单轮5×5矩阵另存round_confusion_matrices。",
                "training_predictions.csv保存每折训练预测；repeated_cv_oof_predictions.csv只保存验证预测及ID。",
                "sample_prediction_stability.csv记录每个开发样本20次预测中的错误频率，颜色或样本编号均不参与拟合。", "",
                f"首轮与原五折对照：{json.dumps(summary['first_round_comparison'], ensure_ascii=False)}", "",
                "标准差ddof=1，分位数为线性插值，仅描述划分波动；不使用普通t检验、独立样本标准误或置信区间。",
                "所有100折通过ID隔离、全特征数、未拟合初始化以及标准化器样本计数/均值/方差核验。",
                "本次未调参、未减少特征、未启动后续阶段、未训练全开发集最终模型、未评估保留测试集。", "",
                "## 解释边界", "", *summary["interpretation"], "",
                "分数稳定或没有观测到错误，都不等于真实错误率为零，也不证明跨机构、平台或人群具有同样性能。该数据只包含五类已患癌样本。",
                "负对照若开启，应与真实标签结果分开报告；用置乱标签重新分层，不能要求其折成员与真实标签完全相同。"]
        (output / "重复交叉验证结果说明.md").write_text("\n".join(text) + "\n", encoding="utf-8")
        status.update(status="complete", n_cv_evaluations_completed=100,
                      elapsed_seconds=time.perf_counter() - start, all_fold_audits_passed=True)
        write_json(output / "stage_status.json", status)
        pointer = "latest_repeated_permutation.json" if permute_labels else "latest_repeated_cv.json"
        write_json(cfg.output_dir / pointer, {"run_directory": str(output.relative_to(cfg.output_dir)), "status": "complete"})
        print(f"完成100折：Macro-F1={m['mean']:.8f} ± {m['std']:.8f}；范围[{m['min']:.8f}, {m['max']:.8f}]。", flush=True)
        print(f"错误总次数={summary['total_oof_error_count']}，出现错误样本数={summary['n_samples_with_any_error']}。", flush=True)
        print(f"结果目录：{output}", flush=True)
        return output
    except Exception as exc:
        status.update(status="failed", error=str(exc), elapsed_seconds=time.perf_counter() - start)
        progress = output / "cv_progress.json"
        if progress.exists():
            status["n_cv_evaluations_completed"] = _read_json(progress)["completed_evaluations"]
        write_json(output / "stage_status.json", status)
        (output / "error_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    # 共用main参数解析，避免两个入口的默认配置发生漂移。
    from main import main
    raise SystemExit(main(["--stage", "1", "--cv-mode", "repeated", *__import__("sys").argv[1:]]))
