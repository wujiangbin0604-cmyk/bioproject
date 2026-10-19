# -*- coding: utf-8 -*-
"""三模型硬投票的七幅真实结果图；复用统一中文字体与330 DPI/PDF保存函数。"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from config import CLASS_ORDER
from hard_voting import ALL_MODELS
from visualization import _save, configure_fonts

COLORS = ("#3777A6", "#D38A39", "#8967AC", "#308775")
LABELS = ("A：ANOVA\nTop50 + SVM", "B：高方差\nTop50 + SVM", "C：ANOVA\nTop50 + LR", "等权硬投票\n三模型")


def performance_plot(folds, rounds, output, metric, label, filename):
    rng = np.random.default_rng(42)
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.3), layout="constrained")
    minimum = min(folds[f"validation_{metric}"].min(), rounds[f"oof_{metric}"].min())
    lower = max(0., minimum - max(.002, (1 - minimum) * .16))
    for ax, table, column, title in ((axes[0], folds, f"validation_{metric}", "100个验证折（每折128人）"),
                                     (axes[1], rounds, f"oof_{metric}", "20轮完整OOF（每轮640人）")):
        series = [table.loc[table.model.eq(m), column].to_numpy() for m in ALL_MODELS]
        boxes = ax.boxplot(series, positions=np.arange(4), widths=.48, patch_artist=True, showfliers=False,
                           medianprops={"color": "#222222", "linewidth": 1.4})
        for i, (values, color, box) in enumerate(zip(series, COLORS, boxes["boxes"])):
            box.set(facecolor=color, alpha=.16, edgecolor=color)
            ax.scatter(i + rng.uniform(-.14, .14, len(values)), values, s=15, color=color, alpha=.48, linewidth=0)
            ax.scatter(i, values.mean(), marker="D", s=44, c=color, edgecolors="white", linewidths=.7, zorder=5)
        ax.set(xticks=np.arange(4), xticklabels=LABELS, ylabel=label, title=title, ylim=(lower, 1.0015))
        ax.grid(axis="y", color="#E3E7EB", linewidth=.7)
        ax.set_axisbelow(True)
    fig.suptitle(f"三种基础模型与硬投票：{label}\n纵轴局部放大；散点为真实相关评估，菱形为均值", fontsize=13)
    _save(fig, output, filename)


def plot_all(run):
    configure_fonts()
    output = Path(run) / "figures"
    folds = pd.read_csv(run / "ensemble_fold_results.csv")
    rounds = pd.read_csv(run / "ensemble_round_results.csv")
    oof = pd.read_csv(run / "ensemble_oof_predictions.csv")
    pc = pd.read_csv(run / "ensemble_per_class_summary.csv")
    features = pd.read_csv(run / "ensemble_feature_union.csv")
    corrections = pd.read_csv(run / "ensemble_correction_summary.csv")
    performance_plot(folds, rounds, output, "macro_f1", "Macro-F1", "01_三模型与硬投票MacroF1对比")
    performance_plot(folds, rounds, output, "balanced_accuracy", "Balanced Accuracy", "02_三模型与硬投票BalancedAccuracy对比")

    fig, ax = plt.subplots(figsize=(11.4, 5.7), layout="constrained")
    for i, (model, color) in enumerate(zip(ALL_MODELS, COLORS)):
        group = pc.loc[pc.model.eq(model)].set_index("cancer_type").loc[list(CLASS_ORDER)]
        x = np.arange(5) + (i - 1.5) * .15
        ax.errorbar(x, group.f1_mean, yerr=group.f1_std, fmt="o", capsize=3.5, markersize=6,
                    color=color, label=LABELS[i].replace("\n", " "), linewidth=1.2)
    lower = max(0., float((pc.f1_mean - pc.f1_std).min()) - .002)
    ax.set(xticks=np.arange(5), xticklabels=CLASS_ORDER, ylim=(lower, 1.0035), ylabel="逐类别 F1",
           title="五癌种分类表现：20轮完整OOF均值 ± 样本SD\n纵轴局部放大；误差线是描述性SD，非置信区间")
    ax.grid(axis="y", color="#E3E7EB")
    ax.legend(loc="lower center", ncol=2, frameon=False, fontsize=9)
    _save(fig, output, "03_五癌种F1对比")

    fig, axes = plt.subplots(1, 2, figsize=(11.8, 5.4), layout="constrained")
    values = [int(oof.unanimous.sum()), int((~oof.unanimous & ~oof.all_three_different).sum()), int(oof.all_three_different.sum())]
    for ax, counts, labels, colors, title in (
        (axes[0], values, ["三者完全一致", "两者一致", "三者全部不同"], ["#3777A6", "#D38A39", "#B45D68"], "三模型预测一致性"),
        (axes[1], [int(oof.base_error_count.eq(n).sum()) for n in range(4)], ["0个错误", "1个错误", "2个错误", "3个错误"],
         ["#308775", "#A5C2B6", "#D38A39", "#B45D68"], "基础模型错误数量组合")):
        ax.bar(np.arange(len(counts)), counts, color=colors, width=.62)
        for i, count in enumerate(counts):
            ax.text(i, max(count, 1) * 1.20, f"{count:,}\n{count / len(oof):.3%}", ha="center", va="bottom", fontsize=9)
        ax.set(xticks=np.arange(len(counts)), xticklabels=labels, yscale="log", ylim=(.7, len(oof) * 8),
               ylabel="患者×轮次预测事件数（对数轴）", title=title)
        ax.grid(axis="y", color="#E8EBED", linewidth=.6)
        ax.set_axisbelow(True)
    fig.suptitle("预测一致性与错误互补：12,800个相关OOF事件，来自640名患者\n零事件标记在轴底部；三者全不同固定采用A", fontsize=12)
    _save(fig, output, "04_预测一致性与错误组合")

    errors = np.stack([~oof[f"correct_{m}"].to_numpy() for m in "ABC"])
    intersections, jaccard = np.zeros((3, 3), int), np.zeros((3, 3), float)
    for i in range(3):
        for j in range(3):
            intersections[i, j] = np.sum(errors[i] & errors[j])
            union = np.sum(errors[i] | errors[j])
            jaccard[i, j] = intersections[i, j] / union if union else np.nan
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 5), layout="constrained")
    for ax, matrix, title, fmt in ((axes[0], intersections, "错误事件交集（对角线为自身错误数）", "d"),
                                    (axes[1], jaccard, "错误事件Jaccard：交集 / 并集", ".3f")):
        im = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1 if fmt != "d" else max(1, intersections.max()))
        for i in range(3):
            for j in range(3):
                ax.text(j, i, format(matrix[i, j], fmt), ha="center", va="center", fontsize=12,
                        color="white" if matrix[i, j] > im.get_clim()[1] * .5 else "#222222")
        ax.set(xticks=range(3), yticks=range(3), xticklabels=("A", "B", "C"), yticklabels=("A", "B", "C"), title=title)
        fig.colorbar(im, ax=ax, shrink=.8)
    fig.suptitle("同一患者×同一轮次的模型间错误重合\nA：ANOVA + SVM；B：高方差 + SVM；C：ANOVA + LR", fontsize=12)
    _save(fig, output, "05_模型间错误重合")

    fig, ax = plt.subplots(figsize=(9.8, 5.4), layout="constrained")
    corrections = corrections.set_index("reference_model").loc[list("ABC")]
    for offset, col, color, label in ((-.18, "corrected_events", "#308775", "参考模型错误 → 投票正确"),
                                       (.18, "new_error_events", "#B45D68", "参考模型正确 → 投票错误")):
        bars = ax.bar(np.arange(3) + offset, corrections[col], width=.34, color=color, label=label)
        ax.bar_label(bars, padding=4)
    upper = max(corrections.corrected_events.max(), corrections.new_error_events.max(), 1)
    ax.set(xticks=range(3), xticklabels=LABELS[:3], ylabel="患者×轮次事件数", ylim=(0, upper * 1.4 + 1),
           title="硬投票的纠错与新增错误\n相对每个模型分别统计；三组计数不能相加解释为获益患者数")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(frameon=False, loc="upper left")
    ax.grid(axis="y", color="#E3E7EB")
    ax.set_axisbelow(True)
    _save(fig, output, "06_投票纠错与新增错误")

    fig, ax = plt.subplots(figsize=(9.8, 5.3), layout="constrained")
    counts = features.n_distinct_genes_system.value_counts().sort_index()
    bars = ax.bar(counts.index, counts.values, width=.7, color="#3777A6")
    ax.bar_label(bars, padding=4)
    ax.axvline(features.n_distinct_genes_system.mean(), color="#B45D68", ls="--", linewidth=1.5,
               label=f"均值 {features.n_distinct_genes_system.mean():.2f}个基因")
    ax.set(xticks=np.arange(counts.index.min(), counts.index.max() + 1), ylabel="训练折数量（共100折）",
           xlabel="A ∪ B ∪ C 的不同基因数量（A与C每折相同）", ylim=(0, counts.max() * 1.28),
           title="三模型系统实际需要的基因测量预算\n每个模型50个基因，整个投票系统的并集超过50个")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#E3E7EB")
    ax.set_axisbelow(True)
    _save(fig, output, "07_实际独立基因预算")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    plot_all(parser.parse_args().run)
