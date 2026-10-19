# -*- coding: utf-8 -*-
"""只消费真实K=50对照结果；图中显式区分100个折和20轮OOF。"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from visualization import configure_fonts, _save

ORDER = ("full_linear_svm", "variance_top50_svm", "anova_top50_svm")
COLORS = {ORDER[0]: "#65778A", ORDER[1]: "#38898C", ORDER[2]: "#C45A65"}
LABELS = {ORDER[0]: "全特征\n20,531基因", ORDER[1]: "高方差\nTop50", ORDER[2]: "ANOVA\nTop50"}


def _distribution(ax, arrays, labels, colors, rng, ylabel, title):
    boxes = ax.boxplot(arrays, positions=np.arange(len(arrays)), widths=.36, patch_artist=True,
                       showfliers=False, medianprops={"color": "#222222", "linewidth": 1.4})
    for patch, color in zip(boxes["boxes"], colors):
        patch.set(facecolor=color, alpha=.25)
    for i, (values, color) in enumerate(zip(arrays, colors)):
        # 随机数仅用于点在水平方向的避让，绝不改变真实成绩。
        ax.scatter(i + rng.uniform(-.11, .11, len(values)), values, s=12 if len(values) > 30 else 23,
                   color=color, alpha=.6, zorder=3, edgecolors="none")
        ax.text(i, 1.013, f"均值 {np.mean(values):.5f}\nSD {np.std(values, ddof=1):.5f}",
                ha="center", va="bottom", fontsize=9)
    minimum = min(float(np.min(v)) for v in arrays)
    lower = max(0, min(.95, np.floor(minimum * 20) / 20 - .015))
    ax.set(xticks=np.arange(len(labels)), xticklabels=labels, ylabel=ylabel, ylim=(lower, 1.065), title=title)
    ax.grid(axis="y", color="#E5E8EC", linewidth=.7)
    ax.set_axisbelow(True)


def plot_all(output):
    configure_fonts()
    figures = output / "生成图片"
    read = lambda name: pd.read_csv(output / f"{name}.csv", float_precision="round_trip")
    folds, rounds = read("three_method_fold_results"), read("three_method_round_results")
    rng = np.random.default_rng(42)
    for metric, label, filename in (("macro_f1", "Macro-F1", "01_三种方案Macro_F1对比"),
                                     ("balanced_accuracy", "Balanced Accuracy", "02_三种方案Balanced_Accuracy对比")):
        fig, axes = plt.subplots(1, 2, figsize=(12, 5.8), layout="constrained")
        _distribution(axes[0], [folds.loc[folds.method.eq(m), f"validation_{metric}"].to_numpy() for m in ORDER],
                      [LABELS[m] for m in ORDER], [COLORS[m] for m in ORDER], rng, label, "层级一：100个相关验证折 / 每种方案")
        _distribution(axes[1], [rounds.loc[rounds.method.eq(m), f"oof_{metric}"].to_numpy() for m in ORDER],
                      [LABELS[m] for m in ORDER], [COLORS[m] for m in ORDER], rng, label, "层级二：20轮合并OOF / 每轮640人")
        fig.suptitle(f"固定 C=1.0：三种方案的{label}分布\n点为真实分数，箱线为描述统计；共享开发样本，不作独立实验推断", fontsize=13)
        _save(fig, figures, filename)

    per_class = read("top50_per_class_metrics")
    classes = ("BRCA", "KIRC", "COAD", "LUAD", "PRAD")
    per_class = per_class.loc[per_class.scope.eq("round")]
    fig, ax = plt.subplots(figsize=(10, 5.3), layout="constrained")
    values_all = []
    for i, method in enumerate(ORDER[1:]):
        group = per_class.loc[per_class.method.eq(method)]
        means = [group.loc[group.cancer_type.eq(c), "f1"].mean() for c in classes]
        stds = [group.loc[group.cancer_type.eq(c), "f1"].std(ddof=1) for c in classes]
        values_all.extend(group.f1.to_numpy())
        positions = np.arange(5) + (i - .5) * .18
        ax.errorbar(positions, means, yerr=stds, fmt="o", color=COLORS[method], capsize=4,
                    label=LABELS[method].replace("\n", " "), markersize=6)
        for pos, mean in zip(positions, means):
            ax.text(pos, mean + .012 + i * .012, f"{mean:.4f}", ha="center", fontsize=8, color=COLORS[method])
    ax.set(xticks=np.arange(5), xticklabels=classes, xlabel="癌症类别", ylabel="逐类别F1（每轮合并OOF）",
           ylim=(max(0, min(.9, np.floor(min(values_all) * 10) / 10 - .025)), 1.075),
           title="五类癌症分类表现：20轮合并OOF的均值±样本标准差\n误差线是描述性SD，不是独立样本置信区间")
    ax.grid(axis="y", color="#E5E8EC")
    ax.legend(frameon=False, loc="lower left")
    _save(fig, figures, "03_五类癌症F1对比")

    overlap = read("top50_feature_overlap")
    pairs = read("top50_within_method_pairwise_jaccard")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.3), layout="constrained")
    axes[0].hist(overlap.jaccard, bins=np.linspace(0, 1, 41), color="#8068A8", edgecolor="white")
    axes[0].axvline(overlap.jaccard.mean(), color="#333333", linestyle="--", lw=1,
                    label=f"均值 {overlap.jaccard.mean():.4f}")
    axes[0].set(xlim=(0, 1), xlabel="同折两种Top50的Jaccard", ylabel="相同训练划分的数量",
                title=f"方法间重合：100个配对训练折\n平均重合 {overlap.overlap_count.mean():.2f}/50 个基因")
    axes[0].legend(frameon=False)
    for method in ORDER[1:]:
        scores = pairs.loc[pairs.method.eq(method), "jaccard"]
        axes[1].hist(scores, bins=np.linspace(0, 1, 41), histtype="step", linewidth=2,
                     color=COLORS[method], label=LABELS[method].replace("\n", " ") + f"：均值{scores.mean():.4f}")
    axes[1].set(xlim=(0, 1), xlabel="同方法不同训练折特征集合的Jaccard", ylabel="相关集合对数量",
                title="方法内一致性：每种方法4950个集合对\n辅助描述，不替代RQ2的30次子采样")
    axes[1].legend(frameon=False, fontsize=8.5)
    fig.suptitle("特征选择重合度与跨折一致性（两者含义不同）", fontsize=13)
    _save(fig, figures, "04_特征选择重合度与一致性")

    errors = read("top50_errors_by_cancer")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.3), layout="constrained")
    for i, method in enumerate(ORDER[1:]):
        group = errors.loc[errors.method.eq(method)].set_index("cancer_type").loc[list(classes)]
        positions = np.arange(5) + (i - .5) * .34
        for ax, metric, scale in ((axes[0], "error_count", 1), (axes[1], "error_rate", 100)):
            bars = ax.bar(positions, group[metric] * scale, width=.32, color=COLORS[method],
                          label=LABELS[method].replace("\n", " "), alpha=.9)
            ax.bar_label(bars, labels=[str(int(v)) if metric == "error_count" else f"{v*100:.2f}%" for v in group[metric]],
                         padding=3, fontsize=8)
    for ax in axes:
        ax.set(xticks=np.arange(5), xticklabels=classes, xlabel="真实癌症类别")
        ax.margins(y=.22)
        ax.grid(axis="y", color="#E5E8EC")
        ax.set_axisbelow(True)
        ax.legend(frameon=False)
    axes[0].set(ylabel="重复OOF预测错误次数", title="各癌种错误数量（同一人可能计数多次）")
    axes[1].set(ylabel="该癌种重复预测错误比例（%）", title="按类别预测数量归一化的错误比例")
    fig.suptitle("错误预测分析：每种方案640人 × 20轮\n左右图分别显示错误次数与错误率，避免样本量不均衡造成误读", fontsize=13)
    _save(fig, figures, "05_错误预测与癌种分布")


if __name__ == "__main__":
    import json
    from config import ExperimentConfig
    cfg = ExperimentConfig()
    directory = cfg.output_dir / json.loads((cfg.output_dir / "latest_top50_comparison.json").read_text(encoding="utf-8"))["run_directory"]
    plot_all(directory)
