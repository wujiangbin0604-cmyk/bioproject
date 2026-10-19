# -*- coding: utf-8 -*-
"""当前阶段基线绘图，以及后续性能、稳定性、联合分析的真实结果绘图接口。"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd


def configure_fonts() -> str:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for font in ("Microsoft YaHei", "Noto Sans SC", "SimHei", "SimSun"):
        if font in available:
            break
    else:
        raise RuntimeError("未找到中文字体，请安装 Microsoft YaHei / Noto Sans SC / SimHei")
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False,
                         "figure.facecolor": "white", "axes.facecolor": "white",
                         "axes.spines.top": False, "axes.spines.right": False,
                         "font.size": 10, "pdf.fonttype": 42})
    return font


def _save(fig, output: Path, name: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output / f"{name}.png", dpi=330, bbox_inches="tight", pad_inches=0.16)
    fig.savefig(output / f"{name}.pdf", bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)


def plot_baseline_cv(details: pd.DataFrame, output: Path) -> None:
    """每折训练与验证分数，显示两者差距；完全不读取测试结果。"""
    configure_fonts()
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5), layout="constrained")
    for ax, metric, label in zip(axes, ("macro_f1", "balanced_accuracy"),
                                 ("Macro-F1", "Balanced Accuracy")):
        x = details["evaluation_id"].to_numpy()
        ax.plot(x, details[f"train_{metric}"], "o-", color="#3D6FA5", label="训练折")
        ax.plot(x, details[f"validation_{metric}"], "s-", color="#C45A65", label="验证折")
        ax.fill_between(x, details[f"train_{metric}"], details[f"validation_{metric}"],
                        color="#D7DFE8", alpha=0.6)
        ax.set(xlabel="交叉验证折", ylabel=label, xticks=x, ylim=(0.85, 1.01))
        # 若真实结果低于默认显示区间，自动扩展，绝不裁掉较低分数。
        minimum = min(details[f"train_{metric}"].min(), details[f"validation_{metric}"].min())
        if minimum < 0.86:
            ax.set_ylim(max(0, minimum - 0.05), 1.01)
        ax.grid(axis="y", color="#E5E8EC")
        ax.set_axisbelow(True)
        ax.legend(frameon=False)
    fig.suptitle("全特征 Linear SVM：开发集五折交叉验证", fontsize=14, fontweight="bold")
    _save(fig, output, "阶段一_基线交叉验证性能")


def plot_development_confusion(matrix: pd.DataFrame, output: Path) -> None:
    """这里是开发集折外混淆矩阵，标题明确区别于第五阶段独立测试。"""
    configure_fonts()
    fig, ax = plt.subplots(figsize=(6.3, 5.2), layout="constrained")
    image = ax.imshow(matrix.to_numpy(), cmap="Blues")
    for row in range(len(matrix)):
        for col in range(len(matrix)):
            value = int(matrix.iloc[row, col])
            ax.text(col, row, str(value), ha="center", va="center",
                    color="white" if value > matrix.to_numpy().max() * 0.5 else "#222222")
    ax.set(xticks=np.arange(len(matrix)), yticks=np.arange(len(matrix)),
           xticklabels=matrix.columns, yticklabels=matrix.index,
           xlabel="预测类别", ylabel="真实类别", title="开发集五折折外预测混淆矩阵")
    fig.colorbar(image, ax=ax, label="样本数量", shrink=0.8)
    _save(fig, output, "阶段一_开发集折外混淆矩阵")


def plot_repeated_cv(details: pd.DataFrame, rounds: pd.DataFrame, samples: pd.DataFrame,
                     output: Path, permuted: bool = False) -> None:
    """100折分数、20轮OOF及个体错误次数；完整0至1尺度避免夸大微小波动。"""
    configure_fonts()
    fig, axes = plt.subplots(2, 2, figsize=(12.2, 8.4), layout="constrained")
    for ax, metric, label in zip(axes[0], ("macro_f1", "balanced_accuracy"),
                                 ("Macro-F1", "Balanced Accuracy")):
        x = details.evaluation_id.to_numpy()
        ax.plot(x, details[f"train_{metric}"], color="#3779A9", lw=1.2,
                marker="o", markersize=2.8, label="训练折", alpha=.75)
        ax.plot(x, details[f"validation_{metric}"], color="#C94B55", lw=1.1,
                marker=".", markersize=4, label="验证折", alpha=.85)
        for boundary in range(5, 100, 5):
            ax.axvline(boundary + .5, color="#E5E7EA", lw=.6, zorder=0)
        v = details[f"validation_{metric}"]
        ax.set(xlabel="验证评估序号（每5折为一轮）", ylabel=label,
               xlim=(0, 101), ylim=(0, 1.04), title=f"验证均值 {v.mean():.5f}；标准差 {v.std(ddof=1):.5f}")
        ax.legend(frameon=False, loc="lower right")
        ax.grid(axis="y", color="#E5E8EC", linewidth=.6)
    ax = axes[1, 0]
    ax.plot(rounds["round"], rounds.oof_macro_f1, "o-", color="#C94B55", markersize=4, label="Macro-F1")
    ax.plot(rounds["round"], rounds.oof_balanced_accuracy, "x--", color="#3779A9", markersize=5,
            label="Balanced Accuracy")
    ax.set(xlabel="重复轮次", ylabel="合并640个OOF预测后的指标", xticks=[1, 5, 10, 15, 20],
           ylim=(0, 1.04), title="每轮完整开发集的折外表现")
    ax.grid(axis="y", color="#E5E8EC", linewidth=.6)
    ax.legend(frameon=False, loc="lower right")
    ax = axes[1, 1]
    counts = samples.error_count.value_counts().reindex(range(21), fill_value=0)
    ax.bar(counts.index, counts.values, color="#6C8E87", width=.8)
    for error_count, count in counts.items():
        if count:
            ax.text(error_count, count + max(counts.max() * .018, .5), str(count), ha="center", fontsize=9)
    ax.set(xlabel="每个开发样本在20轮中的错误次数", ylabel="开发样本数量", xlim=(-.8, 20.8),
           xticks=[0, 5, 10, 15, 20], ylim=(0, counts.max() * 1.15 + 1),
           title=f"至少一次错误：{int(samples.error_count.gt(0).sum())}/640 个样本")
    title = "全特征 Linear SVM：开发集5折 × 20轮重复交叉验证"
    if permuted:
        title += "（标签置乱负对照）"
    fig.suptitle(title + "\n固定 C=1.0；相关分数仅作描述，不代表外部泛化能力", fontsize=13)
    _save(fig, output, "repeated_cv_performance")


def plot_k_performance(performance: pd.DataFrame, output: Path) -> None:
    """第二阶段接口，输入每模型/每K已确定配置的CV汇总，未运行不生图。"""
    configure_fonts()
    table = performance.loc[pd.to_numeric(performance["k"], errors="coerce").notna()].copy()
    if table.empty:
        raise ValueError("尚无真实的不同 K 实验结果")
    if table.duplicated(["model_id", "k"]).any():
        raise ValueError("每个模型/K应只有一个已明确的配置，不能混用多个C的结果")
    fig, ax = plt.subplots(figsize=(7.4, 4.8), layout="constrained")
    for name, group in table.groupby("model_id"):
        group = group.assign(k=group.k.astype(int)).sort_values("k")
        ax.errorbar(group.k, group.validation_macro_f1_mean,
                    yerr=group.validation_macro_f1_std, marker="o", capsize=3, label=name)
    ax.set(xscale="log", xlabel="基因特征数量 K（对数坐标）", ylabel="开发CV Macro-F1（均值±标准差）")
    ax.legend(frameon=False)
    _save(fig, output, "阶段二_特征数量与分类性能")


def plot_stability_curve(stability: pd.DataFrame, output: Path) -> None:
    """第三阶段接口：只绘制实际子采样的稳定性结果。"""
    if stability.empty:
        raise ValueError("尚无真实子采样稳定性结果")
    configure_fonts()
    fig, ax = plt.subplots(figsize=(7.4, 4.8), layout="constrained")
    for method, group in stability.groupby("selection_method"):
        group = group.sort_values("k")
        ax.plot(group.k, group.mean_jaccard, "o-", label=method)
    ax.set(xscale="log", xlabel="基因特征数量 K（对数坐标）", ylabel="平均两两 Jaccard", ylim=(0, 1.02))
    ax.legend(frameon=False)
    _save(fig, output, "阶段三_特征选择稳定性")


def plot_performance_stability(performance: pd.DataFrame, stability: pd.DataFrame, output: Path) -> None:
    """第四阶段接口：仅按同一选择器、同一K连接性能和稳定性。

    不能把 ANOVA 的性能移植给系数选择器；没有对应性能的稳定性点不画。
    """
    if stability.duplicated(["selection_method", "k"]).any():
        raise ValueError("稳定性汇总的选择器/K必须唯一")
    table = performance.merge(stability, on=["selection_method", "k"], validate="many_to_one")
    if table.empty:
        raise ValueError("没有同一选择器/K的真实性能和稳定性对照")
    configure_fonts()
    fig, ax = plt.subplots(figsize=(7.4, 4.8), layout="constrained")
    for model, group in table.groupby("model_id"):
        ax.scatter(group.mean_jaccard, group.validation_macro_f1_mean, label=model)
        for row in group.itertuples():
            ax.annotate(f"K={row.k}", (row.mean_jaccard, row.validation_macro_f1_mean),
                        xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.set(xlabel="平均两两 Jaccard", ylabel="开发CV Macro-F1")
    ax.legend(frameon=False)
    _save(fig, output, "阶段四_性能与稳定性")


if __name__ == "__main__":
    print("绘图模块需要真实实验表；由 main.py 在相应阶段调用，未运行阶段不生成占位结果。")
