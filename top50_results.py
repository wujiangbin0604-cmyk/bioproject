# -*- coding: utf-8 -*-
"""K=50受控实验的OOF、类别、错误、配对差值及特征一致性描述统计。"""
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from config import CLASS_ORDER
from data_loader import write_json
from evaluation import compute_metrics
from repeated_cv import descriptive

METHODS = ("variance_top50_svm", "anova_top50_svm")
NAMES = {"full_linear_svm": "全特征Linear SVM", METHODS[0]: "高方差Top50", METHODS[1]: "ANOVA Top50"}


def save(table, output, name):
    table.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")


def summarize_results(output, data, parent, identity):
    read = lambda name: pd.read_csv(output / f"{name}.csv", float_precision="round_trip")
    details, oof, selected = (read(name) for name in (
        "top50_comparison_fold_results", "top50_oof_predictions", "top50_selected_features_by_fold"))
    if len(details) != 200 or len(oof) != 25600 or len(selected) != 10000:
        raise AssertionError("200次拟合、25600次OOF或10000条选中特征记录未完成")
    round_rows, class_rows, confusion_rows = [], [], []
    round_dir = output / "round_oof"
    round_dir.mkdir()
    fold_metrics = [c for c in details if c.startswith(("train_", "validation_", "gap_"))] + ["fit_seconds", "predict_seconds"]

    def per_class(predictions, method, scope, round_id=0, evaluation_id=0):
        precision, recall, f1, support = precision_recall_fscore_support(
            predictions.y_true, predictions.y_pred, labels=list(CLASS_ORDER), zero_division=0)
        for i, label in enumerate(CLASS_ORDER):
            class_rows.append({"method": method, "scope": scope, "round": round_id,
                               "evaluation_id": evaluation_id, "cancer_type": label,
                               "precision": float(precision[i]), "recall": float(recall[i]), "f1": float(f1[i]),
                               "support_prediction_records": int(support[i]),
                               "n_distinct_samples": int(predictions.loc[predictions.y_true.eq(label), "sample_id"].nunique())})

    for (method, evaluation_id), predictions in oof.groupby(["method", "evaluation_id"]):
        per_class(predictions, method, "fold", int(predictions["round"].iloc[0]), int(evaluation_id))
    for (method, round_id), predictions in oof.groupby(["method", "round"]):
        if len(predictions) != 640 or predictions.sample_id.nunique() != 640:
            raise AssertionError("每轮OOF不是固定640人各一次")
        fold = details.loc[details.method.eq(method) & details["round"].eq(round_id)]
        row = {"method": method, "round": int(round_id), "n_oof_samples": 640, "n_folds": 5,
               **{f"oof_{k}": v for k, v in compute_metrics(predictions.y_true, predictions.y_pred).items()},
               "oof_error_count": int(predictions.is_error.sum()), "fit_seconds_sum": float(fold.fit_seconds.sum())}
        for col in fold_metrics:
            row.update({f"{col}_{stat}": value for stat, value in descriptive(fold[col]).items()})
        round_rows.append(row)
        per_class(predictions, method, "round", int(round_id))
        method_dir = round_dir / method
        method_dir.mkdir(exist_ok=True)
        predictions.set_index("sample_id").loc[data.X.index].reset_index().to_csv(
            method_dir / f"round_{round_id:02d}.csv", index=False, encoding="utf-8-sig")
        matrix = confusion_matrix(predictions.y_true, predictions.y_pred, labels=list(CLASS_ORDER))
        for i, true in enumerate(CLASS_ORDER):
            for j, pred in enumerate(CLASS_ORDER):
                confusion_rows.append({"method": method, "scope": "round", "round": int(round_id),
                                       "true_label": true, "predicted_label": pred, "count": int(matrix[i, j])})
    for method, predictions in oof.groupby("method"):
        per_class(predictions, method, "pooled_repeated_oof")
    rounds = pd.DataFrame(round_rows)
    save(rounds, output, "top50_comparison_round_results")
    save(pd.DataFrame(class_rows), output, "top50_per_class_metrics")
    save(pd.DataFrame(confusion_rows), output, "top50_confusion_matrices")

    sample_rows, cancer_rows = [], []
    for method, predictions in oof.groupby("method"):
        for sid, group in predictions.groupby("sample_id", sort=False):
            if len(group) != 20 or group.y_true.nunique() != 1:
                raise AssertionError("每个样本必须有20次OOF且真实标签一致")
            counts = group.y_pred.value_counts().reindex(CLASS_ORDER, fill_value=0)
            sample_rows.append({"method": method, "sample_id": sid, "cancer_type": group.y_true.iloc[0],
                                "n_predictions": 20, "error_count": int(group.is_error.sum()),
                                "error_rate": float(group.is_error.mean()), "modal_prediction": counts.idxmax(),
                                "error_rounds": ";".join(map(str, group.loc[group.is_error, "round"])),
                                **{f"predicted_{c}_count": int(counts[c]) for c in CLASS_ORDER}})
        for label in CLASS_ORDER:
            group = predictions.loc[predictions.y_true.eq(label)]
            cancer_rows.append({"method": method, "cancer_type": label, "n_development_samples": int(data.y.eq(label).sum()),
                                "n_repeated_predictions": len(group), "error_count": int(group.is_error.sum()),
                                "error_rate": float(group.is_error.mean()),
                                "n_distinct_samples_with_errors": int(group.loc[group.is_error, "sample_id"].nunique())})
    samples = pd.DataFrame(sample_rows)
    save(samples, output, "top50_sample_error_frequency")
    save(pd.DataFrame(cancer_rows), output, "top50_errors_by_cancer")
    save(oof.loc[oof.is_error], output, "top50_error_predictions")

    feature_sets = {(method, int(evaluation)): set(group.gene_id)
                    for (method, evaluation), group in selected.groupby(["method", "evaluation_id"])}
    overlap_rows = []
    for evaluation_id in range(1, 101):
        a, b = (feature_sets[(method, evaluation_id)] for method in METHODS)
        common, union = a & b, a | b
        overlap_rows.append({"evaluation_id": evaluation_id, "round": (evaluation_id - 1) // 5 + 1,
                             "fold": (evaluation_id - 1) % 5 + 1, "overlap_count": len(common),
                             "union_count": len(union), "jaccard": len(common) / len(union),
                             "overlap_gene_ids": ";".join(sorted(common, key=lambda g: int(g.split('_')[1])))})
    overlap = pd.DataFrame(overlap_rows)
    save(overlap, output, "top50_feature_overlap")
    frequency_rows, pairwise_rows, stability_rows = [], [], []
    folds = __import__("json").loads((output / "cv_fold_indices.json").read_text(encoding="utf-8"))["folds"]
    training_ids = {f["evaluation_id"]: set(f["train_sample_ids"]) for f in folds}
    for method in METHODS:
        frequencies = selected.loc[selected.method.eq(method)].gene_id.value_counts().reindex(data.X.columns, fill_value=0)
        for gene, count in frequencies.items():
            frequency_rows.append({"method": method, "gene_id": gene, "selected_fold_count": int(count),
                                   "n_training_folds": 100, "selection_frequency": float(count / 100)})
        js = []
        for i, j in combinations(range(1, 101), 2):
            a, b = feature_sets[(method, i)], feature_sets[(method, j)]
            score = len(a & b) / len(a | b)
            js.append(score)
            pairwise_rows.append({"method": method, "evaluation_i": i, "evaluation_j": j,
                                  "jaccard": score, "n_common_training_samples": len(training_ids[i] & training_ids[j]),
                                  "same_round": (i - 1) // 5 == (j - 1) // 5})
        stability_rows.append({"method": method, "n_feature_sets": 100, "n_pairs": 4950,
                               "n_genes_ever_selected": int(frequencies.gt(0).sum()),
                               "n_genes_selected_in_all_100_folds": int(frequencies.eq(100).sum()),
                               **{f"jaccard_{k}": v for k, v in descriptive(js).items()}})
    stability = pd.DataFrame(stability_rows)
    save(pd.DataFrame(frequency_rows), output, "top50_feature_selection_frequency")
    save(pd.DataFrame(pairwise_rows), output, "top50_within_method_pairwise_jaccard")
    save(stability, output, "top50_feature_stability_summary")

    baseline_folds = pd.read_csv(parent / "repeated_cv_fold_results.csv", float_precision="round_trip").assign(method="full_linear_svm")
    baseline_rounds = pd.read_csv(parent / "repeated_cv_round_summary.csv", float_precision="round_trip").assign(method="full_linear_svm")
    all_folds = pd.concat([baseline_folds, details], ignore_index=True)
    all_rounds = pd.concat([baseline_rounds, rounds], ignore_index=True)
    save(all_folds, output, "three_method_fold_results")
    save(all_rounds, output, "three_method_round_results")
    summary_rows = []
    for method in ("full_linear_svm", *METHODS):
        fold, rnd = all_folds.loc[all_folds.method.eq(method)], all_rounds.loc[all_rounds.method.eq(method)]
        row = {"method": method, "k": 20531 if method == "full_linear_svm" else 50, "C": 1.0,
               "source": "previous_completed_run" if method == "full_linear_svm" else "current_run",
               "n_validation_folds": 100, "n_oof_rounds": 20,
               "baseline_pairing_verified": identity["paired_baseline_comparison_allowed"],
               "perfect_validation_folds": int(fold.validation_macro_f1.eq(1).sum()),
               "perfect_oof_rounds": int(rnd.oof_error_count.eq(0).sum()),
               "total_repeated_oof_errors": int(rnd.oof_error_count.sum())}
        for col in fold_metrics:
            row.update({f"{col}_{stat}": value for stat, value in descriptive(fold[col]).items()})
        for col in ("oof_macro_f1", "oof_balanced_accuracy", "oof_error_count"):
            row.update({f"round_{col}_{stat}": value for stat, value in descriptive(rnd[col]).items()})
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)
    save(summary, output, "top50_comparison_summary")

    paired_summaries = {}
    for level, table, key, metrics in (
        ("fold", all_folds, "evaluation_id", ["validation_macro_f1", "validation_balanced_accuracy", "gap_macro_f1", "gap_balanced_accuracy"]),
        ("round", all_rounds, "round", ["oof_macro_f1", "oof_balanced_accuracy", "oof_error_count"])):
        comparisons = [(METHODS[1], METHODS[0])]
        if identity["paired_baseline_comparison_allowed"]:
            comparisons += [(m, "full_linear_svm") for m in METHODS]
        differences = []
        for first, second in comparisons:
            a, b = table.loc[table.method.eq(first)].set_index(key), table.loc[table.method.eq(second)].set_index(key)
            for evaluation_id in sorted(a.index):
                differences.append({key: int(evaluation_id), "method_A": first, "method_B": second,
                                    "difference_definition": "A_minus_B",
                                    **{f"delta_{metric}": float(a.loc[evaluation_id, metric] - b.loc[evaluation_id, metric]) for metric in metrics}})
        differences = pd.DataFrame(differences)
        save(differences, output, f"top50_paired_{level}_differences")
        paired_summaries[level] = []
        for (first, second), group in differences.groupby(["method_A", "method_B"]):
            paired_summaries[level].append({"method_A": first, "method_B": second,
                **{metric: {**descriptive(group[metric]), "n_positive": int(group[metric].gt(1e-12).sum()),
                            "n_negative": int(group[metric].lt(-1e-12).sum()), "n_ties": int(group[metric].abs().le(1e-12).sum())}
                   for metric in differences if metric.startswith("delta_")}})
    write_json(output / "comparison_descriptive_statistics.json", {
        "cross_method_feature_overlap": {k: descriptive(overlap[k]) for k in ("overlap_count", "jaccard")},
        "paired_score_differences": paired_summaries,
        "std_ddof": 1, "quantiles": [.05, .25, .5, .75, .95], "tie_tolerance_for_performance": 1e-12,
        "independent_sample_tests_performed": False, "confidence_intervals_computed": False,
        "baseline_pairing_verified": identity["paired_baseline_comparison_allowed"],
        "new_classifier_fits": 200, "baseline_refits": 0, "n_development_samples": 640,
        "n_predictions_per_method": 12800, "rq2_30_subsampling_performed": False})
    write_report(output, summary, pd.DataFrame(cancer_rows), stability, overlap, identity)


def write_report(output, summary, errors, stability, overlap, identity):
    table = summary.set_index("method")
    a, b, full = (table.loc[m] for m in (*METHODS, "full_linear_svm"))
    delta = float(b.validation_macro_f1_mean - a.validation_macro_f1_mean)
    delta_ba = float(b.validation_balanced_accuracy_mean - a.validation_balanced_accuracy_mean)
    higher = "ANOVA Top50" if delta > 1e-12 else ("高方差Top50" if delta < -1e-12 else "两者相同")
    stable = stability.set_index("method")
    j_delta = stable.loc[METHODS[1], "jaccard_mean"] - stable.loc[METHODS[0], "jaccard_mean"]
    more_stable = "ANOVA Top50" if j_delta > 1e-12 else ("高方差Top50" if j_delta < -1e-12 else "两者相同")
    visual = ("本次Macro-F1均值方向与ANOVA热图更整齐的探索观察一致，但图像不构成独立预测证据。" if delta > 1e-12 else
              "本次结果未支持仅凭ANOVA热图更整齐就判断其分类性能更高。")
    fold_stability = "较小" if b.validation_macro_f1_std < a.validation_macro_f1_std else ("较大" if b.validation_macro_f1_std > a.validation_macro_f1_std else "相同")
    round_stability = "较小" if b.round_oof_macro_f1_std < a.round_oof_macro_f1_std else ("较大" if b.round_oof_macro_f1_std > a.round_oof_macro_f1_std else "相同")
    paired = pd.read_csv(output / "top50_paired_fold_differences.csv", float_precision="round_trip")
    paired = paired.loc[paired.method_A.eq(METHODS[1]) & paired.method_B.eq(METHODS[0])]
    delta_f = paired.delta_validation_macro_f1
    sample_errors = pd.read_csv(output / "top50_sample_error_frequency.csv")
    sample_errors = sample_errors.loc[sample_errors.error_count.gt(0)].sort_values(["sample_id", "method"])
    lines = ["# 高方差Top50与ANOVA Top50：固定配置配对重复CV", "",
             "## 实验范围与审计", "",
             "使用原固定640个开发样本及全部20,531个基因作为每折选择器输入。保留161行只核对ID、不解析其表达值或标签；顺序读取TAR文件物理字节不构成使用测试表达/标签。",
             "100组同一训练/验证索引，每组分别拟合两条Pipeline，共200次新分类器拟合。K=50，C=1.0，dual='auto'；其他模型参数复用原基线，未调参、未执行其他K、未运行最终测试。",
             "重复分层5折×20轮，random_state=42。每折512训练、128验证；选择器→StandardScaler→LinearSVC每折全部重新拟合。fit审计追踪各步骤的实际输入、调用次数、原表达值、所选50列、标准化均值/方差和ID隔离。",
             "方差使用训练折原表达尺度、ddof=1，并列按原列号从小到大；ANOVA严格使用原版SelectKBest(f_classif,k=50)，并列规则由其稳定排序决定。恒定基因F=NaN保留诊断，非恒定NaN、无穷值或负分数会停止。",
             "每折完整训练评分数组见training_fold_feature_scores.npz，实际所选基因及其评分见top50_selected_features_by_fold.csv；不读取先前探索Top50名单。",
             f"原全特征基线逐折配对资格核验：**{identity['paired_baseline_comparison_allowed']}**；详细核对见baseline_identity_audit.json；基线未重新拟合。", "",
             "## 实际性能", "", "|方案|100折Macro-F1均值±SD|100折Balanced Accuracy均值±SD|20轮Macro-F1均值±SD|重复OOF错误次数|",
             "|---|---|---|---|---|"]
    for method in ("full_linear_svm", *METHODS):
        row = table.loc[method]
        lines.append(f"|{NAMES[method]}|{row.validation_macro_f1_mean:.8f} ± {row.validation_macro_f1_std:.8f}|"
                     f"{row.validation_balanced_accuracy_mean:.8f} ± {row.validation_balanced_accuracy_std:.8f}|"
                     f"{row.round_oof_macro_f1_mean:.8f} ± {row.round_oof_macro_f1_std:.8f}|{int(row.total_repeated_oof_errors)}|")
    lines += ["", "均值、样本标准差ddof=1、最小/最大及分位数见summary CSV。20轮指标先合并每轮640条OOF再评分，不等于把100折分数按独立样本分析。",
              f"性能划分稳定性必须注明层级：ANOVA的100折Macro-F1 SD={b.validation_macro_f1_std:.8f}，相对方差方法{a.validation_macro_f1_std:.8f}为{fold_stability}；但20轮合并OOF Macro-F1 SD={b.round_oof_macro_f1_std:.8f}，相对方差方法{a.round_oof_macro_f1_std:.8f}为{round_stability}。不能把一个层级的较小SD推广为全面更稳定。",
              f"同折配对Macro-F1：ANOVA较高{int(delta_f.gt(1e-12).sum())}折、较低{int(delta_f.lt(-1e-12).sum())}折、相同{int(delta_f.abs().le(1e-12).sum())}折；这只是相关折的描述次数，不据此进行普通二项检验。", "",
              "## 七个研究问题", "",
              f"1. **Macro-F1哪种更高？** 本次均值为{higher}；ANOVA−方差={delta:+.8f}（{delta*100:+.5f}个百分点）。",
              f"2. **Balanced Accuracy差异？** ANOVA−方差={delta_ba:+.8f}（{delta_ba*100:+.5f}个百分点）。这是本数据划分下的描述差异，不能用未经设计的独立样本检验宣称显著或等效。",
              "3. **易错癌种？** 下表同时给出重复错误次数与按类别预测次数归一化的错误率，避免类别数量不等导致误读。", "",
              "|方法|癌种|重复预测错误次数|重复预测错误比例|出现错误的不同开发样本数|", "|---|---|---:|---:|---:|"]
    for _, row in errors.iterrows():
        lines.append(f"|{NAMES[row.method]}|{row.cancer_type}|{int(row.error_count)}|{row.error_rate:.4%}|{int(row.n_distinct_samples_with_errors)}|")
    lines += ["", "患者级错误集中情况如下，每人每方法均被折外预测20次：", "",
              "|方法|样本ID|真实癌种|20轮错误次数|错误比例|", "|---|---|---|---:|---:|"]
    for row in sample_errors.itertuples():
        lines.append(f"|{NAMES[row.method]}|{row.sample_id}|{row.cancer_type}|{row.error_count}|{row.error_rate:.0%}|")
    lines += ["", "不同方法在同一患者上的错误次数可能方向相反，整体均值优势不代表每个个体都改善；误分类进入另一癌种也会影响该癌种的Precision/F1，即使其真实样本没有被误判。"]
    lines += ["", f"4. **两种集合重合？** 同折重合数均值={overlap.overlap_count.mean():.4f}，范围{overlap.overlap_count.min()}–{overlap.overlap_count.max()}；Jaccard均值={overlap.jaccard.mean():.6f}，SD={overlap.jaccard.std(ddof=1):.6f}，范围{overlap.jaccard.min():.6f}–{overlap.jaccard.max():.6f}。",
              f"5. **哪种选择更稳定？** 按100个训练折特征集合两两Jaccard的均值，结果为{more_stable}。高方差={stable.loc[METHODS[0], 'jaccard_mean']:.6f}，ANOVA={stable.loc[METHODS[1], 'jaccard_mean']:.6f}。",
              "每种方法有4950个相关集合对，训练样本高度重叠；这些是描述性辅助稳定性，不能替代RQ2预定的30次分层子采样，也不等于生物学重要性。入选频率包括全部20,531个基因。",
              f"6. **视觉与性能是否一致？** {visual} 每个CV训练折都重新选择基因，所用50个基因并非固定为原热图的全开发集Top50。热图按标签选基因并预设排序的外观不能证明分类优势。",
              f"7. **相对全特征变化？** 特征由20,531减为50，减少{(1-50/20531)*100:.5f}%。高方差Macro-F1均值变化={(a.validation_macro_f1_mean-full.validation_macro_f1_mean)*100:+.5f}个百分点；ANOVA为{(b.validation_macro_f1_mean-full.validation_macro_f1_mean)*100:+.5f}个百分点。",
              f"Balanced Accuracy均值变化：高方差={(a.validation_balanced_accuracy_mean-full.validation_balanced_accuracy_mean)*100:+.5f}个百分点；ANOVA={(b.validation_balanced_accuracy_mean-full.validation_balanced_accuracy_mean)*100:+.5f}个百分点。", "",
              "## 解释限制", "",
              "100个折分数、20轮OOF及特征集合对均共享同一640个样本，存在相关性；不进行独立样本显著性检验、普通标准误或独立样本置信区间。每种方法12,800次OOF预测不代表12,800个患者。",
              "较高均值、较小划分SD和较高特征Jaccard是不同概念，应分别报告。预先查看全开发数据的EDA及据此提出比较也需披露；此实验属于开发阶段受控比较，不是完全未接触数据的确认性检验。",
              "这只能描述内部划分性能，无法确认外部队列、平台或临床应用的泛化能力。161个保留样本未参与本次实验；此前全数据EDA接触过该队列，仍不应称其为从未接触的外部验证。",
              "本次结果不自动确定最终模型或参数；不把这些重复分数用于再次调参后宣称无偏性能。也不能推断其他K或复杂模型的表现。",
              "计时包含整条Pipeline fit（含选择器）；原全特征计时来自历史运行，机器负载可能不同。dual='auto'会随输入维度自动选择求解方式，参数保持一致，不手动改动。", "",
              "## 文件与复现", "", "所有PNG与PDF在生成图片/。每折原始预测、训练预测、每轮OOF、逐类指标、样本错误、配对差值、完整特征评分、日志和源代码快照均保存。", "",
              "```powershell", "python top50_comparison.py", "python verify_top50_comparison.py", "```", "",
              "只汇总既有预测/重新绘图可用top50_results.summarize_results和top50_visualization.plot_all，不应为排版重新拟合模型。"]
    (output / "Top50对照实验报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
