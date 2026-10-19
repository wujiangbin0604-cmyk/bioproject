# -*- coding: utf-8 -*-
"""复算K=50实验统计、训练折排名和预测；不新增任何分类器拟合。"""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.metrics import precision_recall_fscore_support

from config import CLASS_ORDER, ExperimentConfig
from cross_validation import make_cv
from data_loader import load_existing_development_data, write_json
from evaluation import compute_metrics

METHODS = ("variance_top50_svm", "anova_top50_svm")


def verify(output, data):
    checks = []
    read = lambda name: pd.read_csv(output / f"{name}.csv", float_precision="round_trip")
    read_json = lambda name: json.loads((output / f"{name}.json").read_text(encoding="utf-8"))

    def check(name, condition):
        if not bool(condition):
            raise AssertionError(f"验收失败：{name}")
        checks.append(name)

    def close(name, a, b, rtol=1e-9, atol=1e-11):
        check(name, np.allclose(a, b, rtol=rtol, atol=atol, equal_nan=True))

    folds = read("top50_comparison_fold_results")
    oof = read("top50_oof_predictions")
    training = read("top50_training_predictions")
    selected = read("top50_selected_features_by_fold")
    audit = read("top50_cv_fit_audit")
    rounds = read("top50_comparison_round_results")
    summary = read("top50_comparison_summary")
    samples = read("top50_sample_error_frequency")
    overlap = read("top50_feature_overlap")
    per_class = read("top50_per_class_metrics")
    frequency = read("top50_feature_selection_frequency")
    pairs = read("top50_within_method_pairwise_jaccard")
    saved_splits = read_json("cv_fold_indices")["folds"]
    identity, data_record = read_json("baseline_identity_audit"), read_json("development_data_record")
    check("仅解析开发表达和标签", data_record["strict_development_rows_only_parsed"] is True
          and data.X.shape == (640, 20531) and data.X.index.equals(data.y.index))
    check("数据记录与既有基线配对核验通过", identity["paired_baseline_comparison_allowed"] == all(identity["checks"].values()))
    cfg_output = ExperimentConfig().output_dir
    original_directory = cfg_output / identity["source_directory"]
    frozen_original = json.loads((original_directory / "frozen_pipeline.json").read_text(encoding="utf-8"))
    frozen_new = read_json("frozen_pipelines")
    for method in METHODS:
        check(f"{method}除选择器外与原始全特征流程完全一致",
              frozen_new[method]["pipeline_steps"][1:] == frozen_original["pipeline_steps"])
    check("200折结果、25600个验证预测、102400个训练预测和10000个选中特征",
          (len(folds), len(oof), len(training), len(selected), len(audit)) == (200, 25600, 102400, 10000, 200))
    check("固定K50、C1及每折20531输入", folds.k.eq(50).all() and folds.C.eq(1).all()
          and folds.n_features_input.eq(20531).all() and folds.n_features_model.eq(50).all())
    check("验证记录没有保留ID", not set(oof.sample_id) & set(data.reserved_test_ids))
    check("训练记录没有保留ID", not set(training.sample_id) & set(data.reserved_test_ids))
    cfg = replace(ExperimentConfig(), cv_mode="repeated")
    score_file = np.load(output / "training_fold_feature_scores.npz")
    check("保存完整200组训练折特征评分", len(score_file.files) == 200)
    selected_sets = {}
    for evaluation_id, ((tr, va), saved) in enumerate(zip(make_cv(cfg).split(data.X, data.y), saved_splits), 1):
        X, y = data.X.iloc[tr], data.y.iloc[tr]
        train_ids, valid_ids = X.index.tolist(), data.X.index[va].tolist()
        check(f"划分{evaluation_id}原始索引及顺序重现", saved["train_sample_ids"] == train_ids and saved["validation_sample_ids"] == valid_ids)
        check(f"划分{evaluation_id}训练验证保留互斥", not set(train_ids) & set(valid_ids)
              and not (set(train_ids) | set(valid_ids)) & set(data.reserved_test_ids))
        a = X.to_numpy(dtype=float)
        variance, grand = a.var(axis=0, ddof=1), a.mean(axis=0)
        constant = np.ptp(a, axis=0) == 0
        ssb, ssw = np.zeros(20531), np.zeros(20531)
        for label in CLASS_ORDER:
            group = a[y.eq(label).to_numpy()]
            mu = group.mean(axis=0)
            ssb += len(group) * (mu - grand) ** 2
            ssw += ((group - mu) ** 2).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            manual_f = ssb / 4 / (ssw / 507)
        manual_f[constant] = np.nan
        for method in METHODS:
            score = score_file[f"{method}__{evaluation_id:03d}"]
            if method == METHODS[0]:
                close(f"{method}/{evaluation_id}完整训练方差复算", score, variance)
                selected_indices = np.argsort(-score, kind="stable")[:50]
            else:
                close(f"{method}/{evaluation_id}完整训练ANOVA独立公式复算", score, manual_f, rtol=1e-6, atol=1e-6)
                check(f"ANOVA/{evaluation_id}仅常量NaN且无无穷值", np.array_equal(np.isnan(score), constant) and not np.isinf(score).any())
                selected_indices = np.argsort(np.where(np.isnan(score), -np.inf, score), kind="mergesort")[-50:]
            feature_rows = selected.loc[selected.method.eq(method) & selected.evaluation_id.eq(evaluation_id)].sort_values("transform_position")
            names = data.X.columns[np.sort(selected_indices)].tolist()
            check(f"{method}/{evaluation_id}恰好50列且变换列顺序正确", feature_rows.gene_id.tolist() == names and len(names) == 50)
            close(f"{method}/{evaluation_id}选中评分准确", feature_rows.selector_score, score[np.sort(selected_indices)])
            selected_sets[(method, evaluation_id)] = set(names)
            val = oof.loc[oof.method.eq(method) & oof.evaluation_id.eq(evaluation_id)]
            train = training.loc[training.method.eq(method) & training.evaluation_id.eq(evaluation_id)]
            check(f"{method}/{evaluation_id}训练验证预测ID准确", val.sample_id.tolist() == valid_ids and train.sample_id.tolist() == train_ids)
            check(f"{method}/{evaluation_id}真实标签一致", np.array_equal(val.y_true, data.y.loc[valid_ids])
                  and np.array_equal(train.y_true, data.y.loc[train_ids]))
            row = folds.loc[folds.method.eq(method) & folds.evaluation_id.eq(evaluation_id)].iloc[0]
            t, v = compute_metrics(train.y_true, train.y_pred), compute_metrics(val.y_true, val.y_pred)
            for metric in t:
                close(f"{method}/{evaluation_id}训练{metric}复算", row[f"train_{metric}"], t[metric])
                close(f"{method}/{evaluation_id}验证{metric}复算", row[f"validation_{metric}"], v[metric])
                close(f"{method}/{evaluation_id}差距{metric}复算", row[f"gap_{metric}"], t[metric] - v[metric])
        cross = overlap.loc[overlap.evaluation_id.eq(evaluation_id)].iloc[0]
        first, second = [selected_sets[(m, evaluation_id)] for m in METHODS]
        check(f"划分{evaluation_id}交集/并集准确", cross.overlap_count == len(first & second) and cross.union_count == len(first | second))
        close(f"划分{evaluation_id}同折Jaccard复算", cross.jaccard, len(first & second) / len(first | second))
    score_file.close()
    close("错误标记准确", oof.is_error.astype(int), oof.y_true.ne(oof.y_pred).astype(int))
    for (method, round_id), group in oof.groupby(["method", "round"]):
        check(f"{method}/轮{round_id}恰好640人一次", len(group) == group.sample_id.nunique() == 640)
        row = rounds.loc[rounds.method.eq(method) & rounds["round"].eq(round_id)].iloc[0]
        for metric, value in compute_metrics(group.y_true, group.y_pred).items():
            close(f"{method}/轮{round_id}合并OOF {metric}", row[f"oof_{metric}"], value)
        close(f"{method}/轮{round_id}错误次数", row.oof_error_count, group.is_error.sum())
    for method in METHODS:
        subset = samples.loc[samples.method.eq(method)].set_index("sample_id")
        counts = oof.loc[oof.method.eq(method)].groupby("sample_id").is_error.agg(["sum", "size"]).loc[subset.index]
        check(f"{method}每人20次预测", counts["size"].eq(20).all())
        close(f"{method}每人错误数及比例", subset.error_count, counts["sum"])
        close(f"{method}每人错误比例", subset.error_rate, counts["sum"] / 20)
        freq = selected.loc[selected.method.eq(method)].gene_id.value_counts().reindex(data.X.columns, fill_value=0)
        actual = frequency.loc[frequency.method.eq(method)].set_index("gene_id").loc[data.X.columns]
        close(f"{method}所有基因入选频数", actual.selected_fold_count, freq)
        close(f"{method}所有基因入选频率", actual.selection_frequency, freq / 100)
        check(f"{method}总入选次数5000", actual.selected_fold_count.sum() == 5000)
        method_pairs = pairs.loc[pairs.method.eq(method)]
        check(f"{method}4950个不同特征集合对", len(method_pairs) == 4950 and not method_pairs.duplicated(["evaluation_i", "evaluation_j"]).any())
        expected = [len(selected_sets[(method, int(r.evaluation_i))] & selected_sets[(method, int(r.evaluation_j))]) /
                    len(selected_sets[(method, int(r.evaluation_i))] | selected_sets[(method, int(r.evaluation_j))])
                    for r in method_pairs.itertuples()]
        close(f"{method}4950个方法内Jaccard复算", method_pairs.jaccard, expected)
    for (method, scope, round_id, evaluation_id), group in per_class.groupby(["method", "scope", "round", "evaluation_id"]):
        pred = oof.loc[oof.method.eq(method)]
        if scope == "fold":
            pred = pred.loc[pred.evaluation_id.eq(evaluation_id)]
        elif scope == "round":
            pred = pred.loc[pred["round"].eq(round_id)]
        p, r, f, n = precision_recall_fscore_support(pred.y_true, pred.y_pred, labels=list(CLASS_ORDER), zero_division=0)
        group = group.set_index("cancer_type").loc[list(CLASS_ORDER)]
        close(f"{method}/{scope}/{round_id}/{evaluation_id}逐类P/R/F及样本量", group[["precision", "recall", "f1", "support_prediction_records"]], np.array([p, r, f, n]).T)
    three = read("three_method_fold_results")
    three_rounds = read("three_method_round_results")
    for row in summary.itertuples():
        part = three.loc[three.method.eq(row.method)]
        for metric in ("train_macro_f1", "validation_macro_f1", "train_balanced_accuracy", "validation_balanced_accuracy", "gap_macro_f1", "gap_balanced_accuracy", "fit_seconds"):
            for stat in ("mean", "std", "min", "max"):
                expected = part[metric].std(ddof=1) if stat == "std" else getattr(part[metric], stat)()
                close(f"{row.method}汇总{metric}_{stat}", getattr(row, f"{metric}_{stat}"), expected)
        part = three_rounds.loc[three_rounds.method.eq(row.method)]
        for metric in ("oof_macro_f1", "oof_balanced_accuracy", "oof_error_count"):
            for stat in ("mean", "std", "min", "max"):
                expected = part[metric].std(ddof=1) if stat == "std" else getattr(part[metric], stat)()
                close(f"{row.method}每轮汇总{metric}_{stat}", getattr(row, f"round_{metric}_{stat}"), expected)
    for level, table, key in (("fold", three, "evaluation_id"), ("round", three_rounds, "round")):
        delta = read(f"top50_paired_{level}_differences")
        for row in delta.itertuples():
            first = table.loc[table.method.eq(row.method_A) & table[key].eq(getattr(row, key))].iloc[0]
            second = table.loc[table.method.eq(row.method_B) & table[key].eq(getattr(row, key))].iloc[0]
            for col in delta:
                if col.startswith("delta_"):
                    close(f"{level}/{getattr(row,key)}/{row.method_A}-{row.method_B}/{col}", getattr(row, col), first[col[6:]] - second[col[6:]])
    for col in ("selector_fit_calls", "scaler_fit_calls", "classifier_fit_calls"):
        check(f"所有200次{col}恰好1", audit[col].eq(1).all())
    check("所有选择器仅fit512行20531列", audit.selector_fit_samples.eq(512).all() and audit.selector_fit_features.eq(20531).all())
    check("所有标准化器仅fit512行50列", audit.scaler_training_samples.eq(512).all() and audit.scaler_features.eq(50).all())
    check("所有分类器50列且C1", audit.model_features_in.eq(50).all() and audit.model_C.eq(1).all())
    check("全部样本隔离审计通过", audit.train_validation_overlap.eq(0).all() and audit.reserved_test_overlap.eq(0).all())
    for col in ("pipeline_unfitted_before_fit", "selector_fit_ids_identical_to_training", "selector_training_scores_audit_passed",
                "scaler_input_is_original_selected_expression", "classifier_input_is_training_scaled", "all_selected_scores_finite", "scaler_fit_audit_passed"):
        check(f"所有{col}通过", audit[col].all())
    diagnostics = read_json("comparison_descriptive_statistics")
    check("未作独立样本推断、无RQ2子采样", all(diagnostics[k] is False for k in (
        "independent_sample_tests_performed", "confidence_intervals_computed", "rq2_30_subsampling_performed")))
    status = read_json("stage_status")
    check("完成200拟合，未重训基线/测试/其他K", status["status"] == "complete" and status["new_classifier_fits_completed"] == 200
          and all(status[k] is False for k in ("full_feature_baseline_refitted", "test_evaluation_performed", "other_k_experiments_started", "hyperparameter_search_performed")))
    warnings = read_json("warnings")["warnings"]
    check("没有收敛警告", not any(w["category"] == "ConvergenceWarning" for w in warnings))
    images = list((output / "生成图片").glob("*.png"))
    check("生成五张PNG", len(images) == 5)
    for path in images:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            check(f"{path.name}高清PNG完整", min(image.info.get("dpi", (0, 0))) >= 300)
        check(f"{path.stem} PDF存在", path.with_suffix(".pdf").read_bytes().startswith(b"%PDF"))
    result = {"passed": True, "n_checks": len(checks), "checks": checks, "additional_classifier_fits": 0,
              "reserved_expression_or_labels_parsed": False}
    write_json(output / "verification.json", result)
    print(f"K=50对照验收通过：{len(checks)}项；未新增模型拟合。", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    cfg = ExperimentConfig()
    output = args.run_dir.resolve() if args.run_dir else cfg.output_dir / json.loads(
        (cfg.output_dir / "latest_top50_comparison.json").read_text(encoding="utf-8"))["run_directory"]
    source = json.loads((output / "development_data_record.json").read_text(encoding="utf-8"))["source"]
    cfg = replace(cfg, raw_archive=Path(source["archive"])) if source["format"] == "tar" else replace(cfg, data_dir=Path(source["data"]).parent)
    with TemporaryDirectory(prefix="verify_top50_", dir=cfg.output_dir) as temp:
        data = load_existing_development_data(cfg, Path(temp), strict_rows_only=True)
        verify(output, data)
