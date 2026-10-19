# -*- coding: utf-8 -*-
"""七类融合图，只读取真实CSV；330DPI、PDF及清晰的统计层级。"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ablation_engine import atomic_json
from fusion_analysis import RULE_LABELS
from visualization import configure_fonts, _save

FIXED = ("anova", "variance", "fusion_equal", "fusion_anova75", "fusion_variance75")
SHORT = ("ANOVA", "高方差", "等比例融合", "ANOVA75%", "高方差75%")
COLORS = {"anova": "#C35A56", "variance": "#3C78A8", "fusion_equal": "#8C6BB1", "fusion_anova75": "#4F8C73",
          "fusion_variance75": "#D49A45", "intersection": "#799B89", "union": "#A578AD", "anova_only": "#CC8E86",
          "variance_only": "#85A9C5", "anova_matched_union": "#A84242", "variance_matched_union": "#225D90", "add_variance": "#8C6BB1"}


def plot_all(run):
    font = configure_fonts()
    summary = pd.read_csv(run / "fusion_cv_summary.csv")
    fold = pd.read_csv(run / "fusion_cv_fold_results.csv")
    stability = pd.read_csv(run / "fusion_feature_stability.csv")
    errors = pd.read_csv(run / "fusion_sample_errors.csv")
    paired = pd.read_csv(run / "fusion_paired_summary.csv")
    output = run / "figures"
    x = np.arange(5)
    for number, metric, label in ((1, "macro_f1", "Macro-F1"), (2, "balanced_accuracy", "Balanced Accuracy")):
        fig, axes = plt.subplots(2, 2, figsize=(12.8, 8.5), layout="constrained")
        for col, k in enumerate((20, 50)):
            group = summary.set_index("scheme").loc[[f"{r}_k{k}" for r in FIXED]]
            means, std = group[f"validation_{metric}_mean"].to_numpy(), group[f"validation_{metric}_std"].to_numpy()
            for row in (0, 1):
                ax = axes[row, col]
                for i, rule in enumerate(FIXED):
                    ax.errorbar(i, means[i], yerr=std[i], color=COLORS[rule], marker="o", capsize=4, ms=6)
                ax.set(xticks=x, xticklabels=SHORT, ylabel=label,
                       title=f"K={k}：{'完整尺度' if row == 0 else '局部放大'}")
                ax.tick_params(axis="x", labelrotation=12, labelsize=9)
                ax.grid(axis="y", color="#E5E8EC", lw=.6)
                ax.set_ylim((0, 1.04) if row == 0 else (max(0, np.nanmin(means-std)-.002), min(1.04, np.nanmax(means+std)+.002)))
                if row == 1:
                    for i, value in enumerate(means):
                        ax.annotate(f"{value:.6f}", (i, value), xytext=(0, 10), textcoords="offset points", ha="center", fontsize=8)
        fig.suptitle(f"固定特征预算下的融合比例与{label}\n640开发样本；5折×20轮；100相关验证折的均值 ± 样本SD（非置信区间）", fontsize=12)
        _save(fig, output, f"{number:02d}_融合比例与{label.replace(' ', '')}对比")
    rules = ("anova", "variance", "intersection", "union", "anova_only", "variance_only", "anova_matched_union", "variance_matched_union")
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.4), layout="constrained")
    for col, k in enumerate((20, 50)):
        names = [f"{r}_k{k}" for r in rules]
        sizes = [fold.loc[fold.scheme.eq(n), "n_features"].to_numpy() for n in names]
        boxes = axes[0, col].boxplot(sizes, positions=np.arange(len(names)), widths=.6, patch_artist=True, showfliers=True)
        for patch, rule in zip(boxes["boxes"], rules):
            patch.set_facecolor(COLORS[rule])
            patch.set_alpha(.65)
        axes[0, col].set(ylabel="当前训练折的实际特征数", title=f"原始K={k}：集合数量分布")
        group = summary.set_index("scheme").loc[names]
        for i, rule in enumerate(rules):
            axes[1, col].errorbar(i, group.validation_macro_f1_mean.iloc[i], yerr=group.validation_macro_f1_std.iloc[i],
                                 color=COLORS[rule], marker="o", capsize=3)
        axes[1, col].set(ylabel="验证 Macro-F1（均值 ± 样本SD）", title="匹配M对照与并集在同一训练折数量相同")
        low = min(0.95, float((group.validation_macro_f1_mean - group.validation_macro_f1_std).min()) - .02)
        axes[1, col].set_ylim(max(0, low), 1.025)
        for row in (0, 1):
            axes[row, col].set_xticks(np.arange(len(names)), [RULE_LABELS[r] for r in rules], rotation=25, ha="right", fontsize=9)
            axes[row, col].grid(axis="y", color="#E5E8EC", lw=.6)
    fig.suptitle("交集、并集与独有基因：数量及分类表现\n640开发样本；100个相关CV训练/验证折；可变数量集合仅作互补性探索", fontsize=12)
    _save(fig, output, "03_交集并集独有基因数量与性能")
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 5.4), layout="constrained")
    definitions = [("anova", ["anova_k50", "anova_k60", "anova_k70", "anova_k80"], "ANOVA单方法"),
                   ("variance", ["variance_k50", "variance_k60", "variance_k70", "variance_k80"], "高方差单方法"),
                   ("add_variance", ["anova_k50", "add_variance_10", "add_variance_20", "add_variance_30"], "ANOVA50+高方差未入选基因")]
    lows, highs = [], []
    for ax in axes:
        for rule, names, label in definitions:
            group = summary.set_index("scheme").loc[names]
            means, stds = group.validation_macro_f1_mean.to_numpy(), group.validation_macro_f1_std.to_numpy()
            ax.errorbar([50, 60, 70, 80], means, yerr=stds, color=COLORS[rule], marker="o", capsize=3, label=label)
            lows.extend(means - stds)
            highs.extend(means + stds)
        ax.set(xticks=[50, 60, 70, 80], xlabel="实际特征数量", ylabel="验证 Macro-F1")
        ax.grid(axis="y", color="#E5E8EC", lw=.6)
    axes[0].set(ylim=(0, 1.04), title="完整尺度")
    axes[0].legend(frameon=False, loc="lower right", fontsize=9)
    axes[1].set(ylim=(max(0, min(lows)-.002), min(1.04, max(highs)+.002)), title="局部放大：相同数量对照")
    fig.suptitle("逐步补充高方差候选基因的分类表现\n640开发样本；100相关验证折均值±样本SD；新增基因只按当前训练折排名", fontsize=12)
    _save(fig, output, "04_逐步补充基因数量与性能")
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 5.6), layout="constrained")
    for ax, k in zip(axes, (20, 50)):
        g = stability.set_index("scheme").loc[[f"{r}_k{k}" for r in FIXED]]
        for i, rule in enumerate(FIXED):
            ax.bar(i, g.jaccard_mean.iloc[i], yerr=g.jaccard_std.iloc[i], color=COLORS[rule], alpha=.85, capsize=3, width=.65)
            ax.text(i, g.jaccard_mean.iloc[i]+g.jaccard_std.iloc[i]+.015, f"{g.jaccard_mean.iloc[i]:.4f}", ha="center", fontsize=9)
        ax.set(xticks=x, xticklabels=SHORT, ylabel="平均两两 Jaccard", ylim=(0, 1.06), title=f"固定 K={k}")
        ax.tick_params(axis="x", labelrotation=12, labelsize=9)
        ax.grid(axis="y", color="#E5E8EC", lw=.6)
        ax.set_axisbelow(True)
    fig.suptitle("固定预算融合方案的特征选择稳定性\n复用30组512/640分层子采样；435个相关配对均值±样本SD；可变集合另表报告", fontsize=12)
    _save(fig, output, "05_固定预算融合Jaccard对比")
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 9), layout="constrained")
    for col, k in enumerate((20, 50)):
        for i, rule in enumerate(FIXED):
            g = errors.loc[errors.scheme.eq(f"{rule}_k{k}")]
            axes[0, col].bar(i, g.error_count.sum(), color=COLORS[rule], width=.65)
            axes[0, col].text(i, g.error_count.sum()+.6, str(int(g.error_count.sum())), ha="center", fontsize=9)
        axes[0, col].set(xticks=x, xticklabels=SHORT, ylabel="20轮OOF累计错误预测次数", title=f"K={k}：每患者重复预测20次")
        axes[0, col].tick_params(axis="x", labelrotation=12, labelsize=9)
        contrasts = paired.loc[paired.target.str.startswith("fusion") & paired.target.str.endswith(f"_k{k}") & paired.reference.eq(f"anova_k{k}")]
        z = np.arange(len(contrasts))
        axes[1, col].bar(z-.18, contrasts.n_rescued_predictions, color="#4F8C73", width=.35, label="原ANOVA错误→融合正确")
        axes[1, col].bar(z+.18, contrasts.n_new_error_predictions, color="#C35A56", width=.35, label="原ANOVA正确→融合错误")
        labels = [RULE_LABELS[v.split("_k")[0]] for v in contrasts.target]
        axes[1, col].set(xticks=z, xticklabels=labels, ylabel="同一验证患者的预测变化次数", title="救回与新增错误同时报告")
        axes[1, col].tick_params(axis="x", labelrotation=12, labelsize=9)
        axes[1, col].legend(frameon=False, fontsize=8)
        for row in (0, 1):
            axes[row, col].grid(axis="y", color="#E5E8EC", lw=.6)
            axes[row, col].set_axisbelow(True)
    fig.suptitle("单方法与融合的错误预测分析\n640开发样本；5折×20轮；预测次数不是独立患者数，完整患者ID及转变另存CSV", fontsize=12)
    _save(fig, output, "06_单方法与融合错误样本对比")
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 5.8), layout="constrained", sharey=True)
    for ax, fixed in zip(axes, (True, False)):
        group = summary.loc[summary.fixed_budget.eq(fixed)]
        for rule, g in group.groupby("rule", sort=False):
            ax.scatter(g.n_features_mean, g.validation_macro_f1_mean, color=COLORS[rule], s=55, label=RULE_LABELS[rule], edgecolor="white", lw=.5)
        ax.set(xlabel="实际特征数量（可变集合为100折均值）", ylabel="平均验证 Macro-F1", title="固定预算与逐步补充方案" if fixed else "可变集合及匹配M对照")
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        ax.grid(color="#E5E8EC", lw=.6)
    axes[0].set_ylim(max(0, summary.validation_macro_f1_mean.min()-.03), 1.015)
    fig.suptitle("特征数量与分类性能：31个预先固定方案\n640开发样本；100个相关验证折；可变集合的均值数量不代表统一特征预算", fontsize=12)
    _save(fig, output, "07_特征数量与性能散点图")
    atomic_json(output / "figure_provenance.json", {"font": font, "dpi": 330, "format": ["PNG", "PDF"],
                "sources": ["fusion_cv_summary.csv", "fusion_cv_fold_results.csv", "fusion_feature_stability.csv", "fusion_sample_errors.csv", "fusion_paired_summary.csv"],
                "all_data_real": True, "error_bars": "descriptive sample SD; dependent folds/pairs, not confidence intervals"})
