"""Whitelist-backed adapters for the project's saved, real experiment outputs.

This module never reads raw expression matrices, patient prediction tables, or
test sample IDs. Each response is assembled from a small set of known summary
files and labels its provenance for the UI.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(os.environ.get("GENESCOPE_PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()
CLASS_ORDER = ("BRCA", "KIRC", "COAD", "LUAD", "PRAD")
CLASS_LABELS = {
    "BRCA": "乳腺浸润性癌",
    "KIRC": "肾透明细胞癌",
    "COAD": "结肠腺癌",
    "LUAD": "肺腺癌",
    "PRAD": "前列腺腺癌",
}
K_VALUES = (20, 50, 100, 300, 500, 1000)

RUNS: dict[str, dict[str, str]] = {
    "baseline": {"pointer": "latest_stage1.json", "label": "阶段一基线"},
    "heatmaps": {"pointer": "latest_development_heatmaps.json", "label": "开发集探索性热图"},
    "ablation": {"pointer": "latest_full_feature_ablation.json", "label": "特征数量消融"},
    "fusion": {"pointer": "latest_feature_fusion.json", "label": "特征融合"},
    "voting": {"pointer": "latest_hard_voting_ensemble.json", "label": "三模型硬投票"},
    "arbitration": {"pointer": "latest_dynamic_arbitration.json", "label": "动态仲裁"},
    "holdout": {"pointer": "latest_final_holdout_evaluation.json", "label": "回顾性保留集评价"},
}

FILES: dict[str, dict[str, str]] = {
    "quality": {"run": "baseline", "path": "data_quality.json", "source": "阶段一数据质量报告"},
    "class_distribution": {"run": "baseline", "path": "class_distribution.csv", "source": "阶段一类别统计"},
    "cv_summary": {"run": "ablation", "path": "classification/cv_summary.csv", "source": "开发集重复分层交叉验证"},
    "stability": {"run": "ablation", "path": "stability/stability_summary.csv", "source": "开发集30次分层子采样稳定性分析"},
    "frequency": {"run": "ablation", "path": "stability/feature_selection_frequency.csv", "source": "开发集30次子采样基因入选频率"},
    "fusion_summary": {"run": "fusion", "path": "fusion_cv_summary.csv", "source": "开发集特征融合重复交叉验证"},
    "fusion_overlap": {"run": "fusion", "path": "fusion_feature_overlap_summary.csv", "source": "开发集ANOVA与高方差特征集合重合"},
    "fusion_paired": {"run": "fusion", "path": "fusion_paired_summary.csv", "source": "相同折上的开发集配对描述统计"},
    "voting_summary": {"run": "voting", "path": "ensemble_results_table.csv", "source": "开发集重复交叉验证硬投票汇总"},
    "voting_errors": {"run": "voting", "path": "ensemble_error_complementarity.csv", "source": "开发集重复OOF错误互补汇总"},
    "arbitration_summary": {"run": "arbitration", "path": "evaluation/arbitration_results_table.csv", "source": "开发集外层交叉验证动态仲裁结果"},
    "test_summary": {"run": "holdout", "path": "final_test_summary.csv", "source": "161例回顾性保留集评价"},
    "test_per_class": {"run": "holdout", "path": "final_test_per_class_metrics.csv", "source": "161例回顾性保留集逐类别指标"},
    "confusion": {"run": "holdout", "path": "final_confusion_matrices.csv", "source": "161例回顾性保留集混淆矩阵"},
    "error_overlap": {"run": "holdout", "path": "final_error_overlap.csv", "source": "161例回顾性保留集错误重合计数"},
    "error_changes": {"run": "holdout", "path": "final_M4_M5_error_changes_vs_M1.csv", "source": "相对M1的M4/M5纠错与新增错误汇总"},
}

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "class_distribution": {"subset", "cancer_type", "n_samples", "percentage"},
    "cv_summary": {"method", "k", "level", "n", "validation_macro_f1_mean", "validation_balanced_accuracy_mean", "validation_accuracy_mean"},
    "stability": {"method", "k", "n_sets", "jaccard_mean", "jaccard_std", "jaccard_median", "kuncheva_mean"},
    "frequency": {"method", "k", "gene_id", "selection_count", "selection_frequency", "mean_rank_when_selected", "n_subsamples"},
    "fusion_summary": {"scheme", "k", "validation_macro_f1_mean", "validation_balanced_accuracy_mean", "validation_accuracy_mean", "n_features_mean"},
    "fusion_overlap": {"k", "intersection_mean", "union_mean", "jaccard_mean"},
    "fusion_paired": {"target", "reference", "n_paired_folds", "delta_macro_f1_mean", "delta_balanced_accuracy_mean", "n_rescued_predictions", "n_new_error_predictions"},
    "voting_summary": {"方案", "100折Macro-F1均值", "Balanced Accuracy均值", "Accuracy均值"},
    "voting_errors": {"scope", "kind", "category", "count", "affected_unique_patients"},
    "arbitration_summary": {"方案", "100折Macro-F1均值", "100折Balanced Accuracy均值"},
    "test_summary": {"model", "model_name", "n_test", "n_errors", "accuracy", "accuracy_wilson95_low", "accuracy_wilson95_high", "macro_f1", "macro_f1_stratified_bootstrap95_low", "macro_f1_stratified_bootstrap95_high", "balanced_accuracy", "n_unique_genes", "development_macro_f1_100fold_mean", "development_macro_f1_20round_oof_mean", "development_balanced_accuracy_100fold_mean"},
    "test_per_class": {"model", "model_name", "cancer_type", "precision", "recall", "f1", "support"},
    "confusion": {"model", "true_class", "predicted_class", "count"},
    "error_overlap": {"model_a", "model_b", "shared_error_sample_count"},
    "error_changes": {"comparison", "sample_id", "change"},
}


class ResultUnavailable(RuntimeError):
    """A result is absent or not marked complete."""


class ResultFormatError(RuntimeError):
    """A saved result is malformed or does not match its expected contract."""


def _plain(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(key): _plain(value) for key, value in row.items()} for row in frame.to_dict(orient="records")]


class ResultsRepository:
    """Resolve only registered result pointers and files under the project results directory."""

    def __init__(self, project_root: Path | str = PROJECT_ROOT):
        self.root = Path(project_root).resolve()
        self.results_root = (self.root / "results").resolve()
        self._run_cache: dict[str, Path | None] = {}
        self._csv_cache: dict[str, pd.DataFrame] = {}
        self._json_cache: dict[str, dict[str, Any]] = {}

    def _run(self, run_key: str) -> Path | None:
        if run_key in self._run_cache:
            return self._run_cache[run_key]
        config = RUNS[run_key]
        pointer_path = self.results_root / config["pointer"]
        if not pointer_path.is_file():
            self._run_cache[run_key] = None
            return None
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            relative = Path(str(pointer.get("run_directory", "")))
            if pointer.get("status") != "complete" or relative.is_absolute() or ".." in relative.parts:
                raise ResultFormatError(f"实验指针 {config['pointer']} 的状态或目录字段无效")
            run_path = (self.results_root / relative).resolve()
            if not run_path.is_relative_to(self.results_root) or not run_path.is_dir():
                raise ResultFormatError(f"实验指针 {config['pointer']} 指向了无效结果目录")
        except ResultFormatError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ResultFormatError(f"实验指针 {config['pointer']} 无法读取") from exc
        self._run_cache[run_key] = run_path
        return run_path

    def _file(self, file_key: str) -> Path:
        spec = FILES[file_key]
        run = self._run(spec["run"])
        if run is None:
            raise ResultUnavailable(f"{RUNS[spec['run']]['label']}结果尚未导入或未完成")
        target = (run / spec["path"]).resolve()
        if not target.is_relative_to(run) or not target.is_file():
            raise ResultUnavailable(f"{RUNS[spec['run']]['label']}的汇总文件尚未导入")
        return target

    def _json(self, file_key: str) -> dict[str, Any]:
        if file_key in self._json_cache:
            return self._json_cache[file_key]
        path = self._file(file_key)
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResultFormatError(f"真实结果文件 {path.name} 格式无效") from exc
        if not isinstance(content, dict):
            raise ResultFormatError(f"真实结果文件 {path.name} 应为JSON对象")
        self._json_cache[file_key] = content
        return content

    def _csv(self, file_key: str) -> pd.DataFrame:
        if file_key in self._csv_cache:
            return self._csv_cache[file_key]
        path = self._file(file_key)
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ResultFormatError(f"结果文件 {path.name} 超过API读取上限")
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as exc:
            raise ResultFormatError(f"真实结果文件 {path.name} 无法解析") from exc
        missing = REQUIRED_COLUMNS.get(file_key, set()) - set(frame.columns)
        if missing:
            raise ResultFormatError(f"真实结果文件 {path.name} 缺少必要字段：{sorted(missing)}")
        self._csv_cache[file_key] = frame
        return frame

    def _run_file_exists(self, run_key: str, relative: str) -> bool:
        run = self._run(run_key)
        return bool(run and (run / relative).resolve().is_relative_to(run) and (run / relative).is_file())

    def experiment_status(self) -> dict[str, Any]:
        checks = {
            "dataset_quality": ("quality", "真实数据质量报告"),
            "development_cv": ("cv_summary", "开发集特征数量消融"),
            "selection_stability": ("stability", "30次特征选择稳定性"),
            "feature_frequency": ("frequency", "基因入选频率"),
            "feature_fusion": ("fusion_summary", "特征融合消融"),
            "hard_voting": ("voting_summary", "三模型硬投票"),
            "dynamic_arbitration": ("arbitration_summary", "动态仲裁"),
            "retrospective_holdout": ("test_summary", "回顾性保留集评价"),
        }
        items = []
        for key, (file_key, label) in checks.items():
            try:
                if file_key == "quality":
                    self._json(file_key)
                else:
                    self._csv(file_key)
                items.append({"id": key, "name": label, "status": "available", "verified_summary": True})
            except ResultUnavailable as exc:
                items.append({"id": key, "name": label, "status": "unavailable", "verified_summary": False, "message": str(exc)})
            except ResultFormatError as exc:
                items.append({"id": key, "name": label, "status": "invalid", "verified_summary": False, "message": str(exc)})
        return {"experiments": items, "available_count": sum(x["status"] == "available" for x in items),
                "total_count": len(items), "patient_level_outputs_exposed": False,
                "heatmaps_available": all(self._run_file_exists("heatmaps", f"生成图片/{name}") for name in (
                    "01_方差Top50_患者级热图.png", "03_ANOVA_Top50_患者级热图.png"))}

    def dataset_summary(self) -> dict[str, Any]:
        quality = self._json("quality")
        classes = self._csv("class_distribution")
        all_counts = classes.loc[classes["subset"] == "all_quality_check_only"]
        dev_counts = classes.loc[classes["subset"] == "development"]
        test_counts = classes.loc[classes["subset"] == "reserved_test"]

        def class_records(rows: pd.DataFrame) -> list[dict[str, Any]]:
            return [{"code": str(row.cancer_type), "label": CLASS_LABELS.get(str(row.cancer_type), str(row.cancer_type)),
                     "sample_count": int(row.n_samples), "percentage": round(float(row.percentage), 4)}
                    for row in rows.itertuples(index=False) if str(row.cancer_type) in CLASS_ORDER]

        if int(quality.get("n_samples", 0)) != 801 or int(quality.get("n_genes", 0)) != 20531:
            raise ResultFormatError("数据质量报告维度与项目数据定义不一致")
        return {
            "dataset": {"name": "Gene Expression Cancer RNA-Seq Dataset", "repository": "UCI Dataset 401",
                        "samples": 801, "genes": 20531, "classes": 5,
                        "scope": "五类已患癌肿瘤表达类别比较"},
            "classes": class_records(all_counts),
            "split": {"development_samples": int(dev_counts.n_samples.sum()),
                      "reserved_samples": int(test_counts.n_samples.sum()),
                      "development_percent": 80.0, "reserved_percent": 20.0,
                      "random_state": 42, "stratified": True},
            "development_class_counts": class_records(dev_counts),
            "reserved_class_counts": class_records(test_counts),
            "quality": {"missing_values": int(quality.get("missing_values", -1)),
                        "infinite_values": int(quality.get("infinite_values", -1)),
                        "duplicate_expression_ids": int(quality.get("duplicate_expression_ids", -1)),
                        "duplicate_label_ids": int(quality.get("duplicate_label_ids", -1)),
                        "duplicate_expression_profiles": int(quality.get("duplicate_expression_profiles", -1)),
                        "nonnumeric_columns": int(quality.get("nonnumeric_columns", -1)),
                        "labels_aligned_by_id": bool(quality.get("labels_aligned_by_id", False)),
                        "source_order_matches": bool(quality.get("original_order_matches", False))},
            "data_source_note": "项目保存的数据质量报告；页面未读取或传输原始表达矩阵。",
            "holdout_notice": "保留集来自同一数据集，且曾参与早期全样本探索；结果为回顾性检查，不是外部验证。",
        }

    def feature_performance(self, method: str = "all", k: int | None = None) -> dict[str, Any]:
        frame = self._csv("cv_summary")
        labels = {"full_svm": "全特征 Linear SVM", "variance_svm": "高方差 + Linear SVM",
                  "anova_svm": "ANOVA + Linear SVM", "anova_lr": "ANOVA + Logistic Regression"}
        aliases = {"full": ["full_svm"], "variance": ["variance_svm"], "anova": ["anova_svm"],
                   "logistic": ["anova_lr"], "all": list(labels)}
        if method not in aliases:
            raise ValueError("未知特征方法；可选 all、anova、variance、logistic、full")
        rows = frame.loc[(frame["level"] == "validation_fold") & frame["method"].isin(aliases[method])].copy()
        if k is not None:
            rows = rows.loc[pd.to_numeric(rows["k"], errors="coerce") == k]
        rows["method_label"] = rows["method"].map(labels)
        cols = ["method", "method_label", "k", "n", "validation_macro_f1_mean", "validation_macro_f1_std",
                "validation_balanced_accuracy_mean", "validation_accuracy_mean", "gap_macro_f1_mean",
                "oof_macro_f1_mean", "oof_macro_f1_std", "oof_balanced_accuracy_mean"]
        available = [col for col in cols if col in rows.columns]
        rows = rows[available].sort_values(["method", "k"], kind="stable")
        return {"records": _records(rows), "aggregation_level": "100个相关验证折的描述性汇总",
                "n_splits": 5, "n_repeats": 20, "random_state": 42,
                "statistical_note": "重复划分结果存在相关性，不作为独立重复样本进行显著性检验。"}

    def feature_stability(self, method: str = "all", k: int | None = None) -> dict[str, Any]:
        frame = self._csv("stability")
        if method not in {"all", "anova", "variance", "svc_l2"}:
            raise ValueError("未知稳定性方法；可选 all、anova、variance、svc_l2")
        rows = frame if method == "all" else frame.loc[frame["method"] == method]
        if k is not None:
            rows = rows.loc[pd.to_numeric(rows["k"], errors="coerce") == k]
        columns = ["method", "k", "n_sets", "n_pairs", "jaccard_mean", "jaccard_std", "jaccard_median",
                   "kuncheva_mean", "n_always_selected", "n_ever_selected"]
        rows = rows[[col for col in columns if col in rows.columns]].sort_values(["k", "method"], kind="stable")
        return {"records": _records(rows), "n_subsamples": 30, "train_samples_per_subsample": 512,
                "random_state": 42, "statistical_note": "成对集合比较共享子采样，不进行独立样本显著性检验。"}

    def feature_genes(self, method: str, k: int, search: str = "", page: int = 1,
                      page_size: int = 25, sort_by: str = "selection_frequency",
                      descending: bool = True, include_zero: bool = False) -> dict[str, Any]:
        if method not in {"anova", "variance", "svc_l2"}:
            raise ValueError("未知基因入选频率方法")
        if k not in K_VALUES:
            raise ValueError("K必须为20、50、100、300、500或1000")
        if sort_by not in {"selection_frequency", "selection_count", "mean_rank_when_selected", "gene_id"}:
            raise ValueError("不支持该排序字段")
        frame = self._csv("frequency")
        rows = frame.loc[(frame["method"] == method) & (pd.to_numeric(frame["k"], errors="coerce") == k)].copy()
        if not include_zero:
            rows = rows.loc[pd.to_numeric(rows["selection_count"], errors="coerce") > 0]
        if search:
            rows = rows.loc[rows["gene_id"].astype(str).str.contains(search[:64], case=False, regex=False)]
        rows = rows.sort_values(sort_by, ascending=not descending, na_position="last", kind="stable")
        total = len(rows)
        start = (page - 1) * page_size
        visible = rows.iloc[start:start + page_size]
        columns = ["gene_id", "method", "k", "selection_count", "selection_frequency",
                   "mean_rank_when_selected", "n_subsamples"]
        return {"records": _records(visible[columns]), "page": page, "page_size": page_size,
                "total": total, "anonymous_gene_ids": True,
                "note": "统计稳定性不等于生物学功能重要性；gene_* 为匿名特征标识。"}

    def model_comparison(self) -> dict[str, Any]:
        frame = self._csv("test_summary")
        keep = ["model", "model_name", "n_test", "n_errors", "n_unique_genes", "accuracy",
                "accuracy_wilson95_low", "accuracy_wilson95_high", "macro_f1",
                "macro_f1_stratified_bootstrap95_low", "macro_f1_stratified_bootstrap95_high",
                "balanced_accuracy", "development_macro_f1_100fold_mean", "development_macro_f1_20round_oof_mean",
                "development_balanced_accuracy_100fold_mean", "test_minus_development_macro_f1_100fold",
                "test_minus_development_balanced_accuracy_100fold"]
        available = [col for col in keep if col in frame.columns]
        rows = frame[available].sort_values("model", kind="stable")
        return {"models": _records(rows), "test_scope": "同源回顾性保留集；不属于外部验证",
                "cv_scope": "开发集5折×20轮，100个相关折的描述性统计",
                "model_order_frozen": ["M0", "M1", "M2", "M3", "M4", "M5"],
                "primary_model": "M1", "test_sample_count": 161}

    def model_per_class(self, model: str | None = None) -> dict[str, Any]:
        frame = self._csv("test_per_class")
        if model is not None:
            frame = frame.loc[frame["model"] == model]
        frame = frame.loc[frame["cancer_type"].isin(CLASS_ORDER)]
        cols = ["model", "model_name", "cancer_type", "precision", "recall", "f1", "support"]
        return {"records": _records(frame[cols].sort_values(["model", "cancer_type"], kind="stable")),
                "source_scope": "161例回顾性保留集"}

    def model_confusion(self, model: str) -> dict[str, Any]:
        if model not in {"M0", "M1", "M2", "M3", "M4", "M5"}:
            raise ValueError("model_id必须为M0、M1、M2、M3、M4或M5")
        frame = self._csv("confusion")
        rows = frame.loc[frame["model"] == model]
        matrix = []
        for actual in CLASS_ORDER:
            matrix.append([int(rows.loc[(rows.true_class == actual) & (rows.predicted_class == predicted), "count"].sum())
                           for predicted in CLASS_ORDER])
        return {"model": model, "classes": [{"code": c, "label": CLASS_LABELS[c]} for c in CLASS_ORDER],
                "matrix": matrix, "sample_count": sum(map(sum, matrix)),
                "source_scope": "161例回顾性保留集"}

    def model_error_analysis(self) -> dict[str, Any]:
        overlap = self._csv("error_overlap")
        changes = self._csv("error_changes")
        # Keep aggregate counts only; never return test sample identifiers.
        overlap = overlap.loc[overlap["model_a"] < overlap["model_b"]]
        relative = []
        for model in ("M4", "M5"):
            rows = changes.loc[changes["comparison"] == f"{model}_vs_M1"]
            relative.append({
                "model": model,
                "corrected_vs_M1": int((rows["change"] == "纠正M1错误").sum()),
                "new_errors_vs_M1": int((rows["change"] == "新增错误").sum()),
            })
        return {"shared_error_counts": _records(overlap[["model_a", "model_b", "shared_error_sample_count"]]),
                "relative_to_M1": relative,
                "patient_level_predictions_exposed": False,
                "note": "错误数量很少，结果仅作描述性比较。"}

    def fusion_summary(self) -> dict[str, Any]:
        performance = self._csv("fusion_summary")
        overlap = self._csv("fusion_overlap")
        paired = self._csv("fusion_paired")
        voting = self._csv("voting_summary")
        errors = self._csv("voting_errors")
        arbitration = self._csv("arbitration_summary")
        selected_schemes = {"anova_k50", "variance_k50", "fusion_equal_k50", "fusion_anova75_k50",
                            "fusion_variance75_k50", "intersection_k50", "union_k50",
                            "anova_only_k50", "variance_only_k50", "anova_matched_union_k50",
                            "variance_matched_union_k50", "add_variance_10", "add_variance_20",
                            "add_variance_30"}
        shortlist = performance.loc[performance["scheme"].isin(selected_schemes)].copy()
        perf_cols = ["scheme", "k", "increment", "validation_macro_f1_mean", "validation_macro_f1_std",
                     "validation_balanced_accuracy_mean", "validation_accuracy_mean", "n_features_mean"]
        selected_pairs = paired.loc[paired["target"].isin({"fusion_equal_k50", "fusion_anova75_k50",
                                                             "fusion_variance75_k50", "intersection_k50",
                                                             "union_k50", "anova_only_k50", "variance_only_k50",
                                                             "anova_matched_union_k50", "variance_matched_union_k50",
                                                             "add_variance_30"})]
        pair_cols = ["target", "reference", "n_paired_folds", "delta_macro_f1_mean",
                     "delta_balanced_accuracy_mean", "n_rescued_predictions", "n_new_error_predictions"]
        return {
            "feature_overlap": _records(overlap.loc[pd.to_numeric(overlap["k"], errors="coerce") == 50]),
            "fusion_performance": _records(shortlist[[col for col in perf_cols if col in shortlist.columns]]),
            "paired_comparisons": _records(selected_pairs[[col for col in pair_cols if col in selected_pairs.columns]]),
            "hard_voting": _records(voting),
            "hard_voting_error_patterns": _records(errors.loc[errors["scope"] == "all_repeated_oof_events"]),
            "dynamic_arbitration": _records(arbitration),
            "interpretation_note": "不同特征集合均能分类不等于已证明信息互补；融合预算增加及历史模式筛选带来开发集选择偏差。",
            "event_note": "重复OOF事件来自同一批640名开发样本，不能解释为独立患者数。",
        }

    def heatmap_path(self, method: str) -> Path:
        if method not in {"variance", "anova"}:
            raise ValueError("热图方法必须是variance或anova")
        run = self._run("heatmaps")
        if run is None:
            raise ResultUnavailable("开发集热图结果尚未导入")
        filename = "01_方差Top50_患者级热图.png" if method == "variance" else "03_ANOVA_Top50_患者级热图.png"
        candidate = (run / "生成图片" / filename).resolve()
        if not candidate.is_relative_to(run) or not candidate.is_file():
            raise ResultUnavailable("真实开发集热图文件尚未导入")
        return candidate

    def synthetic_example_path(self) -> Path:
        example = (self.root / "deployment" / "examples" / "sample_input.csv").resolve()
        if not example.is_relative_to(self.root) or not example.is_file():
            raise ResultUnavailable("格式示例文件尚未导入")
        return example
