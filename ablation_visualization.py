# -*- coding: utf-8 -*-
"""七类论文图：只读取完整实验实际 CSV；中文字体、330 DPI 和 PDF。"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ablation_report import LABELS
from config import CLASS_ORDER, K_VALUES
from visualization import configure_fonts, _save

COLORS = {"variance_svm": "#3C78A8", "anova_svm": "#C35A56", "anova_lr": "#528B73",
          "variance": "#3C78A8", "anova": "#C35A56", "svc_l2": "#8B6EB0"}
CLASS_COLORS = dict(zip(CLASS_ORDER, ("#4C78A8", "#E59B48", "#59A17E", "#D16B73", "#9972A8")))


def annotate_points(ax, points):
    """按渲染后的文字边界尝试固定偏移，避免密集性能点标签重叠。"""
    ax.figure.canvas.draw()
    renderer = ax.figure.canvas.get_renderer()
    boxes = []
    for px, py, label, color in points:
        for dx, dy in ((4, 7), (4, -15), (-46, 7), (-46, -15), (4, 22), (-46, 22),
                       (4, -29), (-46, -29), (12, 38), (-54, 38), (12, -44), (-54, -44)):
            annotation = ax.annotate(label, (px, py), xytext=(dx, dy), textcoords="offset points",
                                     fontsize=7.5, color=color, zorder=8,
                                     bbox={"facecolor": "white", "edgecolor": "none", "alpha": .86, "pad": .3},
                                     arrowprops={"arrowstyle": "-", "color": color, "lw": .4, "alpha": .7})
            annotation.update_positions(renderer)
            # 文字自身边界不包含引线，便于检测相互遮挡。
            box = matplotlib.text.Text.get_window_extent(annotation, renderer=renderer).expanded(1.06, 1.12)
            inside = ax.bbox.contains(box.x0, box.y0) and ax.bbox.contains(box.x1, box.y1)
            if inside and not any(box.overlaps(old) for old in boxes):
                boxes.append(box)
                break
            annotation.remove()
        else:
            # 极端密集时标到更远处，保留可追踪的引线。
            annotation = ax.annotate(label, (px, py), xytext=(10, -58 - 11 * len(boxes)), textcoords="offset points",
                                     fontsize=7.5, color=color, arrowprops={"arrowstyle": "-", "color": color, "lw": .4})
            annotation.update_positions(renderer)
            boxes.append(matplotlib.text.Text.get_window_extent(annotation, renderer=renderer))


def plot_all(run):
    font = configure_fonts()
    cv = pd.read_csv(run / "classification" / "cv_summary.csv")
    performance = cv.loc[cv.level.eq("validation_fold")]
    stability = pd.read_csv(run / "stability" / "stability_summary.csv")
    frequency = pd.read_csv(run / "stability" / "feature_selection_frequency.csv")
    joint = pd.read_csv(run / "analysis" / "performance_stability_summary.csv")
    perclass = pd.read_csv(run / "analysis" / "per_class_round_summary.csv")
    output = run / "figures"
    x = np.arange(len(K_VALUES))
    subtitle = "固定640个开发样本；5折 × 20轮；均值 ± 样本标准差（100个相关验证折，仅描述）"
    for number, metric, label in ((1, "macro_f1", "Macro-F1"), (2, "balanced_accuracy", "Balanced Accuracy")):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.3), layout="constrained", gridspec_kw={"width_ratios": [1, 1.55]})
        baseline = performance.loc[performance.method.eq("full_svm")].iloc[0]
        lower, upper = [], []
        for ax in axes:
            for method in ("variance_svm", "anova_svm", "anova_lr"):
                g = performance.loc[performance.method.eq(method)].set_index("k").loc[list(K_VALUES)]
                means, stds = g[f"validation_{metric}_mean"].to_numpy(), g[f"validation_{metric}_std"].to_numpy()
                ax.errorbar(x, means, yerr=stds, color=COLORS[method], marker="o", ms=4, capsize=3, lw=1.5, label=LABELS[method])
                lower.extend(means - stds)
                upper.extend(means + stds)
            value = baseline[f"validation_{metric}_mean"]
            ax.axhline(value, color="#555C65", ls="--", lw=1.3, label=f"全特征 SVM ({value:.6f})")
            ax.set(xticks=x, xticklabels=K_VALUES, xlabel="基因数量 K（候选值等间距排列）", ylabel=label)
            ax.grid(axis="y", color="#E1E5E9", lw=.7)
            ax.set_axisbelow(True)
        axes[0].set(ylim=(0, 1.035), title="完整性能尺度")
        axes[0].legend(loc="lower right", fontsize=8.5, frameon=False)
        axes[1].set(ylim=(max(0, min(lower) - .002), min(1.03, max(upper) + .002)), title="局部放大（相同原始分数）")
        fig.suptitle(f"特征数量与 {label}\n{subtitle}", fontsize=12)
        _save(fig, output, f"{number:02d}_K与{label.replace(' ', '')}曲线")
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2), layout="constrained")
    for method in ("variance", "anova", "svc_l2"):
        g = stability.loc[stability.method.eq(method)].set_index("k").loc[list(K_VALUES)]
        axes[0].errorbar(x, g.jaccard_mean, yerr=g.jaccard_std, color=COLORS[method], marker="o", capsize=3, label=LABELS[method])
        axes[1].errorbar(x, g.kuncheva_mean, yerr=g.kuncheva_std, color=COLORS[method], marker="o", capsize=3, label=LABELS[method])
    for ax, ylabel, title in zip(axes, ("平均两两 Jaccard", "平均 Kuncheva 指标"), ("集合重合稳定性", "机会校正的辅助比较")):
        ax.set(xticks=x, xticklabels=K_VALUES, xlabel="基因数量 K", ylabel=ylabel, title=title)
        ax.grid(axis="y", color="#E1E5E9", lw=.7)
        ax.legend(frameon=False, loc="lower right")
    fig.suptitle("特征选择稳定性与基因数量\n30次共享分层子采样（每次512/640）；435个相关配对，误差棒为描述性样本SD", fontsize=12)
    _save(fig, output, "03_K与特征选择稳定性曲线")
    fig, axes = plt.subplots(1, 2, figsize=(12.3, 5.4), layout="constrained")
    annotated = []
    for ax in axes:
        for method in ("variance_svm", "anova_svm"):
            g = joint.loc[joint.method.eq(method)].sort_values("k")
            ax.plot(g.jaccard_mean, g.validation_macro_f1_mean, "o-", color=COLORS[method], label=LABELS[method], ms=6, lw=1.2)
            for i, r in enumerate(g.itertuples()):
                if ax is axes[1]:
                    annotated.append((r.jaccard_mean, r.validation_macro_f1_mean, f"K={r.k}", COLORS[method]))
        ax.set(xlabel="平均两两 Jaccard（30次共享子采样）", ylabel="平均验证 Macro-F1（100个CV折）")
        ax.grid(color="#E7E9ED", lw=.6)
    axes[0].set(ylim=(0, 1.035), title="完整性能尺度")
    axes[0].legend(frameon=False, loc="lower right")
    axes[1].set(ylim=(joint.validation_macro_f1_mean.min() - .001, 1.001), title="局部放大：每点为真实对应方法与 K")
    fig.suptitle("分类性能与基因集合稳定性\n仅连接高方差-SVM和ANOVA-SVM；系数筛选没有对应Top-K分类成绩，不进入此图", fontsize=12)
    annotate_points(axes[1], annotated)
    _save(fig, output, "04_分类性能与特征选择稳定性关系")
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.2), layout="constrained", sharey=True)
    minimum = perclass.loc[perclass.method.ne("full_svm"), "f1_mean"].min()
    for ax, method in zip(axes, ("variance_svm", "anova_svm", "anova_lr")):
        for c in CLASS_ORDER:
            g = perclass.loc[perclass.method.eq(method) & perclass.cancer_type.eq(c)].set_index("k").loc[list(K_VALUES)]
            ax.plot(x, g.f1_mean, "o-", color=CLASS_COLORS[c], label=c, markersize=4, lw=1.3)
        ax.set(xticks=x, xticklabels=K_VALUES, xlabel="基因数量 K", title=LABELS[method], ylim=(max(0, minimum - .005), 1.004))
        ax.grid(axis="y", color="#E1E5E9", lw=.7)
    axes[0].set_ylabel("癌种 F1（20轮合并OOF的均值，局部尺度）")
    axes[-1].legend(frameon=False, loc="lower right", fontsize=9)
    fig.suptitle("不同基因数量下的五癌种分类表现\n固定640开发样本；每轮五折合并后逐类别计算F1；20轮相关结果仅作描述", fontsize=12)
    _save(fig, output, "05_不同K的五癌种F1对比")
    # 每个 K 均展示三种方法前10名；包含每基因全部频率的完整 CSV 另存。
    fig, axes = plt.subplots(6, 3, figsize=(16, 23), layout="constrained")
    for row, k in enumerate(K_VALUES):
        for col, method in enumerate(("variance", "anova", "svc_l2")):
            ax = axes[row, col]
            g = frequency.loc[frequency.method.eq(method) & frequency.k.eq(k)].sort_values(
                ["selection_frequency", "mean_rank_when_selected", "original_column_index"], ascending=[False, True, True]).head(10).iloc[::-1]
            ax.barh(np.arange(len(g)), g.selection_frequency, color=COLORS[method], alpha=.88, height=.68)
            ax.set(yticks=np.arange(len(g)), yticklabels=g.gene_id, xlim=(0, 1.12), xticks=[0, .5, 1], title=f"{LABELS[method]} · K={k}")
            ax.tick_params(axis="y", labelsize=8)
            for i, count in enumerate(g.selection_count):
                ax.text(g.selection_frequency.iloc[i] + .015, i, str(count), va="center", fontsize=8)
            if row == 5:
                ax.set_xlabel("入选比例（柱尾为30次中的入选次数）")
            ax.grid(axis="x", color="#E6E8EB", lw=.5)
            ax.set_axisbelow(True)
    fig.suptitle("重复子采样中最频繁入选的匿名基因（每方法/K前10名）\n30次共享分层子采样；并列时按平均入选名次、原列位置；不代表生物学因果重要性", fontsize=13)
    _save(fig, output, "06_特征入选频率比较")
    fig, ax = plt.subplots(figsize=(9.6, 5.6), layout="constrained")
    for method in ("variance_svm", "anova_svm", "anova_lr"):
        g = performance.loc[performance.method.eq(method)].set_index("k").loc[list(K_VALUES)]
        ax.errorbar(x, g.gap_macro_f1_mean, yerr=g.gap_macro_f1_std, color=COLORS[method], marker="o", capsize=3, label=LABELS[method])
    ax.axhline(0, color="#6E7379", ls="--", lw=1)
    ax.set(xticks=x, xticklabels=K_VALUES, xlabel="基因数量 K", ylabel="训练 Macro-F1 − 验证 Macro-F1",
           title="训练与验证性能差距\n640开发样本；100个相关验证折的均值 ± 样本SD（非置信区间）")
    ax.legend(frameon=False)
    ax.grid(axis="y", color="#E1E5E9", lw=.7)
    _save(fig, output, "07_训练与验证性能差距")
    from ablation_engine import atomic_json
    atomic_json(output / "figure_provenance.json", {"font": font, "dpi": 330, "vector_format": "PDF",
                "all_figures_from_actual_csv": True, "frequency_panels": "top10 each method and K; full top20 CSV also supplied",
                "figure_sources": ["classification/cv_summary.csv", "stability/stability_summary.csv", "stability/feature_selection_frequency.csv",
                                   "analysis/performance_stability_summary.csv", "analysis/per_class_round_summary.csv"]})
