# -*- coding: utf-8 -*-
"""用完成的真实 CSV 生成 RQ1/RQ2/RQ3 描述性报告；不硬编码成绩。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ablation_engine import METHODS, atomic_json, read_json
from ablation_results import save
from config import CLASS_ORDER

LABELS = {"variance_svm": "高方差 + SVM", "anova_svm": "ANOVA + SVM", "anova_lr": "ANOVA + Logistic Regression", "full_svm": "全特征 SVM",
          "variance": "高方差", "anova": "ANOVA", "svc_l2": "SVM 系数 L2"}


def markdown_table(frame):
    """不用额外 tabulate 依赖，保存真正的 Markdown 表。"""
    def cell(v):
        return f"{v:.8f}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(map(str, frame.columns)) + " |",
                       "| " + " | ".join(["---"] * len(frame.columns)) + " |"] +
                      ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False, name=None)])


def build_report(run, cfg):
    cdir, sdir, output = run / "classification", run / "stability", run / "analysis"
    cv = pd.read_csv(cdir / "cv_summary.csv")
    folds = pd.read_csv(cdir / "cv_fold_results.csv")
    rounds = pd.read_csv(cdir / "cv_round_results.csv")
    stability = pd.read_csv(sdir / "stability_summary.csv")
    frequency = pd.read_csv(sdir / "feature_selection_frequency.csv")
    cross = pd.read_csv(sdir / "cross_method_jaccard.csv")
    cross_summary = cross.groupby(["method_a", "method_b", "k"]).agg(
        n_comparisons=("jaccard", "size"), jaccard_mean=("jaccard", "mean"), jaccard_std=("jaccard", "std"),
        jaccard_min=("jaccard", "min"), jaccard_max=("jaccard", "max"), jaccard_median=("jaccard", "median"),
        overlap_mean=("overlap", "mean")).reset_index()
    save(cross_summary, output / "cross_method_jaccard_summary.csv")
    errors = pd.read_csv(cdir / "sample_error_frequency.csv")
    perclass = pd.read_csv(cdir / "per_class_results.csv")
    performance = cv.loc[cv.level.eq("validation_fold")].copy()
    assert len(folds) == 1900 and len(rounds) == 380 and len(stability) == 18 and len(performance) == 19
    baseline = performance.loc[performance.method.eq("full_svm")].iloc[0]
    selected = performance.loc[performance.method.ne("full_svm")].copy()
    selected["selector"] = selected.method.map({"variance_svm": "variance", "anova_svm": "anova", "anova_lr": "anova"})
    joint = selected.merge(stability, left_on=["selector", "k"], right_on=["method", "k"], suffixes=("", "_stability"), validate="many_to_one")
    assert len(joint) == 18 and not joint.method_stability.eq("svc_l2").any()
    joint["macro_f1_change_from_full"] = joint.validation_macro_f1_mean - baseline.validation_macro_f1_mean
    joint["balanced_accuracy_change_from_full"] = joint.validation_balanced_accuracy_mean - baseline.validation_balanced_accuracy_mean
    joint["stability_source"] = "30_shared_stratified_subsamples_512_of_640;435_correlated_pairs"
    joint["performance_source"] = "100_correlated_development_validation_folds"
    save(joint, output / "performance_stability_summary.csv")
    steps = []
    for method, group in joint.groupby("method"):
        records = list(group.sort_values("k").itertuples())
        for a, b in zip(records, records[1:]):
            steps.append({"method": method, "k_from": a.k, "k_to": b.k,
                          "delta_macro_f1": b.validation_macro_f1_mean - a.validation_macro_f1_mean,
                          "delta_jaccard": b.jaccard_mean - a.jaccard_mean,
                          "delta_kuncheva": b.kuncheva_mean - a.kuncheva_mean})
    step_table = pd.DataFrame(steps)
    save(step_table, output / "adjacent_k_changes.csv")
    delta = float(read_json(run / "logs" / "frozen_experiment.json")["candidate_delta"])
    candidates = []
    for method in METHODS:
        group = selected.loc[selected.method.eq(method)].sort_values("k")
        qualifies = (group.validation_macro_f1_mean - baseline.validation_macro_f1_mean).abs().le(delta)
        qualifying_k = group.loc[qualifies, "k"]
        candidate = int(qualifying_k.min()) if len(qualifying_k) else None
        for r in group.itertuples():
            gap = float(baseline.validation_macro_f1_mean - r.validation_macro_f1_mean)
            candidates.append({"method": method, "k": int(r.k), "baseline_macro_f1_mean": float(baseline.validation_macro_f1_mean),
                               "validation_macro_f1_mean": r.validation_macro_f1_mean, "validation_macro_f1_std": r.validation_macro_f1_std,
                               "baseline_minus_model": gap, "absolute_gap": abs(gap), "delta": delta, "qualifies": abs(gap) <= delta,
                               "is_minimal_candidate_within_prelisted_grid": candidate == int(r.k),
                               "selection_scope": "exploratory_development_only;not_global_optimum;not_unbiased_generalization"})
    candidate_table = pd.DataFrame(candidates)
    save(candidate_table, output / "candidate_k_selection.csv")
    paired = pd.read_csv(cdir / "paired_method_differences.csv")
    paired_summary = paired.groupby(["method_a", "method_b", "k"]).agg(
        n=("evaluation_id", "size"), delta_f1_mean=("delta_macro_f1_a_minus_b", "mean"),
        delta_f1_std=("delta_macro_f1_a_minus_b", "std"), delta_f1_min=("delta_macro_f1_a_minus_b", "min"),
        delta_f1_max=("delta_macro_f1_a_minus_b", "max"), delta_ba_mean=("delta_balanced_accuracy_a_minus_b", "mean")).reset_index()
    save(paired_summary, output / "paired_difference_summary.csv")
    error_by_class = errors.groupby(["method", "k", "y_true"]).agg(
        error_predictions=("error_count", "sum"), distinct_samples_with_error=("error_count", lambda x: int((x > 0).sum())), n_samples=("sample_id", "size")).reset_index()
    error_by_class["total_predictions"] = error_by_class.n_samples * 20
    error_by_class["error_rate"] = error_by_class.error_predictions / error_by_class.total_predictions
    save(error_by_class, output / "errors_by_cancer_type.csv")
    top_genes = frequency.sort_values(["selection_frequency", "mean_rank_when_selected", "original_column_index"], ascending=[False, True, True]).groupby(["method", "k"], sort=False).head(20)
    save(top_genes, output / "frequent_genes_top20_by_method_k.csv")
    perclass_summary = perclass.loc[perclass.level.eq("round_oof")].groupby(["method", "k", "cancer_type"]).agg(
        precision_mean=("precision", "mean"), recall_mean=("recall", "mean"), f1_mean=("f1", "mean"),
        f1_std=("f1", "std"), f1_min=("f1", "min"), f1_max=("f1", "max")).reset_index()
    save(perclass_summary, output / "per_class_round_summary.csv")
    sensitivity = perclass_summary.loc[perclass_summary.method.ne("full_svm")].groupby(["method", "cancer_type"]).agg(
        lowest_f1_over_k=("f1_mean", "min"), highest_f1_over_k=("f1_mean", "max")).reset_index()
    sensitivity["f1_range_over_k"] = sensitivity.highest_f1_over_k - sensitivity.lowest_f1_over_k
    save(sensitivity, output / "per_class_k_sensitivity.csv")
    configurations = []
    for r in performance.itertuples():
        configurations.append({"method": r.method, "k": int(r.k), "fold_macro_f1_mean": r.validation_macro_f1_mean,
                               "fold_macro_f1_std": r.validation_macro_f1_std, "fold_balanced_accuracy_mean": r.validation_balanced_accuracy_mean,
                               "fold_accuracy_mean": r.validation_accuracy_mean})
    summary = {"status": "complete_data_aggregation", "scope": "fixed_640_development_only", "reserved_test_numeric_or_labels_accessed": False,
               "n_cv_splits": 100, "n_rounds": 20, "n_classification_configurations_including_baseline": 19,
               "classification_folds": len(folds), "new_classification_fits": int(folds.result_origin.eq("new_fit").sum()),
               "verified_reused_fits": int(folds.result_origin.eq("verified_prior_fit").sum()), "new_coefficient_ranking_fits": 30,
               "k_values": list(cfg.k_values), "candidate_delta": delta, "performance": configurations,
               "candidates": candidate_table.loc[candidate_table.is_minimal_candidate_within_prelisted_grid, ["method", "k", "validation_macro_f1_mean"]].to_dict("records"),
               "stability": stability.drop(columns=["chance_correction_note"]).to_dict("records"),
               "new_classification_convergence_warnings": int(folds.convergence_warning_count.sum()),
               "statistical_inference_performed": False,
               "dependence_warning": "100 CV scores,20 round scores,and435 pairwise Jaccards are correlated; all summaries are descriptive",
               "coefficient_method_performance_evaluated_after_top_k_selection": False,
               "selected_candidate_is_unbiased_generalization_estimate": False}
    atomic_json(output / "experiment_summary.json", summary)
    main_table = performance[["method", "k", "validation_macro_f1_mean", "validation_macro_f1_std", "validation_balanced_accuracy_mean", "validation_accuracy_mean", "gap_macro_f1_mean"]].copy()
    main_table["method"] = main_table.method.map(LABELS)
    stab_table = stability[["method", "k", "jaccard_mean", "jaccard_std", "jaccard_median", "kuncheva_mean", "n_always_selected", "n_ever_selected"]].copy()
    stab_table["method"] = stab_table.method.map(LABELS)
    text = ["# 高维基因表达特征数量消融、分类性能与稳定性研究", "",
            "## 数据范围与预先固定的实验设计", "",
            "仅使用原划分的 640 个开发样本和 20,531 个原始匿名基因列。161 个保留测试样本的表达值和标签不解析、不统计、不评分；顺序读取 TAR 时仅经过其字节并核对首列 ID。全部标签与表达按 ID 对齐。",
            "",
            f"开发集质量检查：`{read_json(run / 'logs' / 'development_quality.json')}`。常数基因保留在原矩阵；ANOVA 常数列的 NaN 原样记录，仅在排名副本中置 -inf；任何其他 NaN/Inf 停止。方差筛选使用原表达样本方差 ddof=1，先筛选再标准化。",
            "",
            "分类：固定 5 折 × 20 轮重复分层交叉验证，seed=42，各配置完全相同的 100 个索引。每折训练 512、验证 128；选择器和 StandardScaler 都在 Pipeline 内重新拟合，C=1，无超参数搜索。LinearSVC dual='auto'。Logistic Regression 为 lbfgs 多分类、L2（sklearn 1.8 的 l1_ratio=0）、max_iter=50000、tol=1e-4。",
            "",
            f"共记录 {len(folds)} 次分类拟合结果：新增 {summary['new_classification_fits']} 次，核验后复用 {summary['verified_reused_fits']} 次。另拟合 30 个仅用于系数排名的全特征 SVM。复用记录的时间是历史实测时间，与当前新增运行的速度不构成硬件受控比较。",
            "",
            "稳定性：另行生成 StratifiedShuffleSplit(n_splits=30,train_size=0.8,random_state=42)，每次 512 个开发样本且所有方法/K 共享。SVM 系数按当前子采样拟合的标准化全特征模型中，每个特征跨五类别系数的 L2 范数排序；每个子采样仅拟合一次并截取六个 K。它是模型驱动排名，没有相应 Top-K 重训后的分类成绩。",
            "",
            "## RQ1：特征数量与分类性能", "", "下表为 100 个相关验证折的描述统计；标准差 ddof=1。不同层级的 20 轮合并 OOF 统计另存 cv_summary.csv，不与折均值混淆。", "",
            markdown_table(main_table), ""]
    for method in METHODS:
        group = selected.loc[selected.method.eq(method)].sort_values("k")
        changes = np.diff(group.validation_macro_f1_mean.to_numpy())
        text.append(f"- {LABELS[method]}：六个 K 的均值{'单调不下降' if np.all(changes >= -1e-12) else '并非单调增加'}；相邻增量依次为 " + ", ".join(f"{d:+.8f}" for d in changes) + "。")
    pivot = selected.pivot(index="k", columns="method", values="validation_macro_f1_mean")
    text += ["", "相同 K 下 ANOVA-SVM 减去高方差-SVM 的平均 Macro-F1 差值：" + "; ".join(f"K={k}: {r.anova_svm-r.variance_svm:+.8f}" for k, r in pivot.iterrows()) + "。此为配对划分的描述差值，不作独立样本显著性检验。",
             "", "Logistic Regression 与 ANOVA-SVM 仅更换分类器；二者的逐折差值和逐类别表现已保存，不能从很小的开发集均值差宣称某算法具有普遍优势。", "",
             f"预先冻结规则为 |全特征均值−当前均值|≤{delta:.3f}，分别在每种流程内选择预列候选的最小 K：", "",
             markdown_table(candidate_table.loc[candidate_table.is_minimal_candidate_within_prelisted_grid, ["method", "k", "validation_macro_f1_mean", "absolute_gap"]]), "",
             "“趋于稳定”在此仅由上述实用容忍阈值作探索性描述，并非通过等效性检验证明。若 K=20 满足，只说明它是本次候选集合中的最小值，不能证明少于 20 个不行。未按单折最高分选型；完整候选和波动均保留。", "",
             "## RQ2：30 次训练子采样下的特征选择稳定性", "", markdown_table(stab_table), ""]
    for k, group in stability.groupby("k"):
        rank = group.sort_values("jaccard_mean", ascending=False)
        text.append(f"- K={k}：平均 Jaccard 从高到低为 " + " > ".join(f"{LABELS[r.method]} {r.jaccard_mean:.6f}" for r in rank.itertuples()) + "。")
    text.append("")
    for method, group in stability.groupby("method"):
        values = group.sort_values("k").jaccard_mean.to_numpy()
        text.append(f"- {LABELS[method]}：平均 Jaccard 随 K {'单调不下降' if np.all(np.diff(values) >= -1e-12) else '并非单调不下降'}；需结合下述机会校正解释。")
    text += ["", "不同方法在同一个子采样中的集合重合（30次匹配比较，区别于方法组内435对）：", "", markdown_table(cross_summary), ""]
    text += ["", "Jaccard 的机会重合随 K 增加；因此补充 Kuncheva=(交集−K²/p)/(K−K²/p)，p=20531，帮助区分集合变大和超出机会的稳定性。该指标仍只作描述，不为 435 个相关比较构造独立观测置信区间。", "",
             "本次 30 次子采样与之前 100 个重复 CV 训练折是两个不同协议，数值不会直接混用。匿名基因的完整入选频率和每种方法/K 的前 20 位已导出。K=50 的频繁入选示例（并列时按平均入选名次、原列号）：", ""]
    for method in ("variance", "anova", "svc_l2"):
        g = top_genes.loc[top_genes.method.eq(method) & top_genes.k.eq(50)].head(10)
        text.append(f"- {LABELS[method]}：" + ", ".join(f"{r.gene_id}({r.selection_count}/30)" for r in g.itertuples()) + "。")
    text += ["", "## RQ3：性能与特征选择稳定性的关系", "",
             "下述比较只连接真实对应的筛选方法和 K。ANOVA-LR 可连接同一 ANOVA 筛选器的稳定性，但这不证明 LR 本身的模型参数稳定；系数排名没有 Top-K 分类成绩，因此不进入性能纵轴。", ""]
    for k in cfg.k_values:
        a = joint.loc[joint.method.eq("anova_svm") & joint.k.eq(k)].iloc[0]
        v = joint.loc[joint.method.eq("variance_svm") & joint.k.eq(k)].iloc[0]
        text.append(f"- K={k}：ANOVA / 高方差 Macro-F1={a.validation_macro_f1_mean:.8f}/{v.validation_macro_f1_mean:.8f}；Jaccard={a.jaccard_mean:.6f}/{v.jaccard_mean:.6f}。性能差={a.validation_macro_f1_mean-v.validation_macro_f1_mean:+.8f}，稳定性差={a.jaccard_mean-v.jaccard_mean:+.6f}。")
    k50a = joint.loc[joint.method.eq("anova_svm") & joint.k.eq(50)].iloc[0]
    k50v = joint.loc[joint.method.eq("variance_svm") & joint.k.eq(50)].iloc[0]
    text += ["", f"K=50 的重点复核：ANOVA-SVM 减去高方差-SVM 的 Macro-F1 差为 {k50a.validation_macro_f1_mean-k50v.validation_macro_f1_mean:+.8f}，30次子采样 Jaccard 差为 {k50a.jaccard_mean-k50v.jaccard_mean:+.8f}。分类差距很小；基因集合稳定性的方向和幅度应由该独立稳定性协议的实际值判断。", "",
             "相邻 K 的性能与稳定性增量（不是相关性检验）：", "", markdown_table(step_table), ""]
    svm_joint = joint.loc[joint.method.isin(["anova_svm", "variance_svm"])]
    best_perf = svm_joint.sort_values("validation_macro_f1_mean", ascending=False).iloc[0]
    best_stab = svm_joint.sort_values("jaccard_mean", ascending=False).iloc[0]
    discordant = []
    for k in cfg.k_values:
        a = joint.loc[joint.method.eq("anova_svm") & joint.k.eq(k)].iloc[0]
        v = joint.loc[joint.method.eq("variance_svm") & joint.k.eq(k)].iloc[0]
        if (a.validation_macro_f1_mean - v.validation_macro_f1_mean) * (a.jaccard_mean - v.jaccard_mean) < 0:
            discordant.append(k)
    text += ["", f"两种 SVM 筛选方案中，最高平均分类分数对应 {LABELS[best_perf.method]} K={int(best_perf.k)}；最高平均 Jaccard 对应 {LABELS[best_stab.method]} K={int(best_stab.k)}（若有并列请以完整表为准）。",
             f"同 K 下性能优势与稳定性优势方向相反的候选为 {discordant}。" + ("这为“更高分类性能不必然对应更稳定的基因集合”提供了本数据和当前扰动协议内的描述性实例。" if discordant else "本次对应比较没有出现严格反向，不能因此证明二者必然一致。"),
             "",
             "小幅性能变化与稳定性变化需同时阅读完整表：接近满分时少数难分类样本即可改变均值，而选择集合是否一致衡量的是另一属性。没有对仅六个 K 或相关重复评估进行确认性相关检验，也未将这些点视为独立实验。", "",
             "## 逐癌种与个体错误", "",
             "各配置、K、癌种的错误预测总次数、至少一次出错的独立患者数和每患者 20 次错误比例已输出。计数中的一次预测是开发样本在某轮的 OOF 结果，不能把同一患者的 20 次预测当成 20 个独立患者。", "",
             markdown_table(error_by_class.loc[error_by_class.error_predictions.gt(0), ["method", "k", "y_true", "error_predictions", "distinct_samples_with_error", "error_rate"]]), "",
             "各癌种对 K 的敏感性以六个候选下的逐类别平均 F1 范围作描述：", "", markdown_table(sensitivity), "",
             "## 解释分层与局限", "",
             "**真实实验支持的观察**：上表中的开发集分类均值、波动、错误模式、候选 K 和子采样 Jaccard 均来自实际预测或实际入选集合。逐折和逐子采样原始证据、索引、输入范围审计、软件环境和源码快照保留，可恢复中断。",
             "",
             "**可能的机制解释**：相关/冗余基因可携带相似分类信息，因此选择器更换部分基因后分类表现仍接近；原表达总方差兼有组内和组间变化，ANOVA 更突出类别间相对组内的变化。这些是与结果相容的解释，本实验没有证明其具体因果机制。",
             "",
             "**尚未验证的假设**：不能由热力图的连续色块直接推导分类优劣；本次分类可以检验该数据上的预测表现，不能验证基因因果作用。未做相关基因模块、外部队列或临床验证；匿名 gene_x 无对应注释，不能声称发现具体致癌基因或临床诊断标志物。",
             "",
             "**实验局限**：数据高维、样本仅 640、来自单个既有五癌种数据集；未评估批次/中心迁移。重复分层 CV 的训练集高度重叠，100 折和 20 轮分数相关；30 个子采样重叠，435 对 Jaccard 更非独立。全部结果描述训练样本扰动下的开发集表现，不能替代独立外部泛化。用同一开发 CV 比较方法并选 K 会引入模型选择乐观偏差，选中均值不是无偏泛化估计。",
             "",
             "161 个保留测试样本仍未使用；后续最终方案确定后才单独进行独立测试。没有新增 C 搜索、未扩大 K 范围、没有启动复杂模型。预先全数据探索不能提供独立验证证据；正式拟合本次均受限于各训练折。", "",
             "这里的“未使用”指本轮模型开发/稳定性实验。早期项目曾进行包含801样本的描述性可视化；最终论文应披露该探索接触，不能把整个研究历史描述为从未观察过保留样本的完全盲测。该历史探索的基因名单没有进入本轮分类流水线。", "",
             "## 异常与审计", "",
             f"新增分类收敛警告数：{summary['new_classification_convergence_warnings']}。常数列所致的预期 ANOVA 警告完整记录在 classification/warnings.csv 和 stability/warnings.csv，未静默忽略；导入拟合的历史警告见 logs/reuse_audit.json 所列原实验目录。",
             "",
             "训练时间包括对应 Pipeline 拟合，预测时间包括训练折及验证折预测；历史复用记录保留历史测量值，不把它们解读为本轮同机负载下的公平速度比较。所有性能/稳定性图只读取上述真实 CSV。"]
    (output / "experiment_report.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    candidate_phrase = "；".join(f"{LABELS[r.method]}为{int(r.k)}" for r in candidate_table.loc[
        candidate_table.is_minimal_candidate_within_prelisted_grid].itertuples())
    concise = ["# 课程论文结论摘要（真实开发集实验）", "",
               f"在固定640个开发样本、5折×20轮共享交叉验证下，全特征线性SVM的平均Macro-F1为{baseline.validation_macro_f1_mean:.8f}。"
               f"按预先确定的平均Macro-F1绝对差不超过0.005规则，预设候选集合内的最小K为：{candidate_phrase}。"
               "这些是开发集探索性候选，不能解释为全局最优或最少必需基因数。", "",
               f"K=50时，ANOVA-SVM与高方差-SVM的平均Macro-F1分别为{k50a.validation_macro_f1_mean:.8f}和{k50v.validation_macro_f1_mean:.8f}；"
               f"另行30次共享分层子采样所得平均两两Jaccard分别为{k50a.jaccard_mean:.6f}和{k50v.jaccard_mean:.6f}。"
               + ("两项指标的优势方向相反，表明较高预测表现不必然对应较稳定的入选基因集合。" if 50 in discordant else "两项指标的对应关系需结合完整K范围解读，不能由分类成绩单独推断特征稳定性。"), "",
               "各K下的方法相对表现与稳定性排名并非先验结论，完整值见实验报告。相关基因的冗余信息可能允许不同特征子集取得近似分类性能，但这一机制尚未被本实验直接验证。"
               "所有重复CV和Jaccard值均为相关的描述性结果，未作独立样本显著性推断。161个保留测试样本未参与本轮实验，当前结果不能替代外部泛化或临床验证。"]
    (output / "论文结论摘要.md").write_text("\n".join(concise) + "\n", encoding="utf-8")
    return summary
