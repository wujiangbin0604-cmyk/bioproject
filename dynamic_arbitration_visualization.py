# -*- coding: utf-8 -*-
"""动态仲裁实验的八张学术风格图表，所有图均由真实保存结果生成。"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from dynamic_arbitration import PATTERNS, SCHEMES, SCHEME_LABELS
from visualization import _save, configure_fonts

COLORS = {"model_A":"#3B6FB6", "model_B":"#E39B36", "model_C":"#3A9678",
          "hard_vote":"#8064A2", "fixed_disagreement":"#CC6677",
          "learned_inner_oof":"#2A788E", "conservative_fallback":"#9B7653"}
MEMBER_COLORS = {"A":"#3B6FB6", "B":"#E39B36", "C":"#3A9678"}


def _style(ax):
    ax.grid(axis="y", color="#E7EAEE", linewidth=.7)
    ax.set_axisbelow(True)


def _tidy(fig, output, name):
    _save(fig, output, name)


def plot_all(run: Path) -> None:
    """保存八张PNG 330 DPI和对应PDF。"""
    run = Path(run)
    out = run / "figures"
    out.mkdir(parents=True, exist_ok=True)
    configure_fonts()
    modes = pd.read_csv(run/"analysis/disagreement_pattern_summary.csv").set_index("pattern").reindex(PATTERNS)
    patients = pd.read_csv(run/"analysis/disagreement_patient_summary.csv")
    folds = pd.read_csv(run/"evaluation/arbitration_fold_results.csv")
    rounds = pd.read_csv(run/"evaluation/arbitration_round_results.csv")
    perclass = pd.read_csv(run/"evaluation/arbitration_per_class_metrics.csv")
    rules = pd.read_csv(run/"arbitration/learned_rules_by_outer_fold.csv")
    triggers = pd.read_csv(run/"arbitration/arbitration_trigger_details.csv")
    changes = pd.read_csv(run/"evaluation/arbitration_error_changes.csv")

    # 1. 历史OOF预测模式的事件数和不同患者数。
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.3), layout="constrained")
    x = np.arange(len(PATTERNS))
    for ax, values, ylabel, title, color in (
        (axes[0], modes.prediction_events, "重复预测事件数", "预测事件", "#4778A8"),
        (axes[1], modes.unique_patients, "不同患者数", "参与患者", "#D17A49")):
        bars = ax.bar(x, values, color=color, width=.68)
        ax.set(xticks=x, xticklabels=PATTERNS, ylabel=ylabel, title=title)
        _style(ax)
        ax.bar_label(bars, padding=3, fontsize=9)
    fig.suptitle("历史开发集 OOF 的三模型分歧模式", fontsize=14, fontweight="bold")
    fig.text(.5, -.015, "事件含同一患者跨20轮重复预测；患者数按 sample ID 去重。", ha="center", fontsize=9)
    _tidy(fig, out, "01_历史三模型预测模式")

    # 2. 历史模式内三个模型正确率，样本支持数同时显示。
    fig, ax = plt.subplots(figsize=(9.2, 4.8), layout="constrained")
    w = .23
    for j, (model, color) in enumerate(zip("ABC", [MEMBER_COLORS[x] for x in "ABC"])):
        vals = pd.to_numeric(modes[f"accuracy_{model}"], errors="coerce").to_numpy()
        bars = ax.bar(x+(j-1)*w, vals, width=w, color=color, label=f"模型 {model}")
        for i, val in enumerate(vals):
            if np.isfinite(val): ax.text(x[i]+(j-1)*w, val+.008, f"{val:.2f}", ha="center", va="bottom", fontsize=7, rotation=90)
    ax.set(xticks=x, xticklabels=[f"{p}\n(n={int(modes.loc[p,'prediction_events'])})" for p in PATTERNS],
           ylabel="历史 OOF 正确率", ylim=(0,1.19), title="不同预测模式下的单模型正确率")
    ax.legend(frameon=False, ncol=3, loc="upper right")
    _style(ax)
    fig.text(.5, -.015, "历史模式由已查看的开发集 OOF 定义，比例仅为探索性描述。", ha="center", fontsize=9)
    _tidy(fig, out, "02_历史分歧模式正确率")

    # 3. 患者级跨轮分歧次数（含0次），避免用事件数替代独立患者数。
    counts = patients.disagreement_events.value_counts().reindex(range(21), fill_value=0).sort_index()
    fig, ax = plt.subplots(figsize=(10.2, 4.5), layout="constrained")
    ax.bar(counts.index, counts.values, color=["#C8D4DF" if i==0 else "#B86B65" for i in counts.index], width=.8)
    ax.set(xlabel="每名患者在20轮中出现分歧的次数", ylabel="患者数（640名）", xticks=np.arange(0,21,2),
           title="历史 OOF 分歧的患者级重复出现次数")
    _style(ax)
    ax.text(.98,.95,f"无分歧：{int(counts.iloc[0])}人\n至少1次：{int((patients.disagreement_events>0).sum())}人",
            transform=ax.transAxes, ha="right", va="top", bbox={"boxstyle":"round,pad=.4","fc":"white","ec":"#D5D9DE"})
    _tidy(fig, out, "03_患者级分歧重复次数")

    # 4. 100外层折分布 + 20轮完整OOF均值/SD，明确相关统计层级。
    fig, axes = plt.subplots(1,2,figsize=(14,5.1),layout="constrained",gridspec_kw={"width_ratios":[1.2,1]})
    order = list(SCHEMES)
    short_labels = {
        "model_A": "模型A",
        "model_B": "模型B",
        "model_C": "模型C",
        "hard_vote": "硬投票",
        "fixed_disagreement": "固定规则*",
        "learned_inner_oof": "内层学习",
        "conservative_fallback": "保守回退",
    }
    box_data=[folds.loc[folds.scheme.eq(s),"macro_f1"].dropna().to_numpy() for s in order]
    bp=axes[0].boxplot(box_data,patch_artist=True,showfliers=False,medianprops={"color":"#20252A","linewidth":1.4})
    for patch,s in zip(bp["boxes"],order): patch.set_facecolor(COLORS[s]);patch.set_alpha(.76)
    for i,s in enumerate(order,1):
        vals=folds.loc[folds.scheme.eq(s),"macro_f1"].to_numpy()
        jitter=np.linspace(-.12,.12,len(vals))
        axes[0].scatter(np.full(len(vals),i)+jitter,vals,s=7,color=COLORS[s],alpha=.27,linewidths=0)
    axes[0].set(xticks=np.arange(1,len(order)+1),xticklabels=[short_labels[s] for s in order],ylabel="Macro-F1",
                title="100个外层验证折分布")
    axes[0].tick_params(axis="x",rotation=25)
    means=rounds.groupby("scheme").macro_f1.agg(["mean","std"]).reindex(order)
    axes[1].bar(np.arange(len(order)),means["mean"],color=[COLORS[s] for s in order],alpha=.8)
    axes[1].errorbar(np.arange(len(order)),means["mean"],yerr=means["std"],fmt="none",ecolor="#333333",capsize=3,lw=1)
    axes[1].set(xticks=np.arange(len(order)),xticklabels=[short_labels[s] for s in order],ylabel="20轮OOF Macro-F1 均值 ± SD",
                title="20个完整OOF轮次描述统计", ylim=(.985, 1.003), yticks=[.985,.990,.995,1.000])
    axes[1].tick_params(axis="x",rotation=25)
    for ax in axes: _style(ax)
    fig.suptitle("基础模型与仲裁方案的 Macro-F1",fontsize=14,fontweight="bold")
    fig.text(.5,-.02,"折与轮次共享开发样本，仅作描述性比较；不将100折视为独立重复实验。右图纵轴截断以显示细微差异；固定规则*为事后探索。",ha="center",fontsize=9)
    _tidy(fig,out,"04_外层MacroF1对比")

    # 5. 六个主要方法每类 Recall / F1 的20轮均值±SD。
    methods=["model_A","model_B","model_C","hard_vote","fixed_disagreement","learned_inner_oof","conservative_fallback"]
    fig,axes=plt.subplots(1,2,figsize=(13.5,5.1),layout="constrained",sharey=True)
    xc=np.arange(5)
    for ax,metric,title in zip(axes,["recall","f1"],["各癌种 Recall","各癌种 F1"]):
        for s in methods:
            # perclass file stores each repeat; summarize across repeated full OOF rounds.
            source=perclass.loc[perclass.level.eq("round_oof") & perclass.scheme.eq(s)]
            summary=source.groupby("cancer_type")[metric].agg(["mean","std"]).reindex(["BRCA","COAD","KIRC","LUAD","PRAD"])
            ax.errorbar(xc,summary["mean"],yerr=summary["std"],marker="o",markersize=3.7,
                        linewidth=1.15,capsize=2,color=COLORS[s],label=SCHEME_LABELS[s])
        ax.set(xticks=xc,xticklabels=["BRCA","COAD","KIRC","LUAD","PRAD"],ylim=(.975,1.01),yticks=[.98,.99,1.00],title=title,ylabel="每轮指标均值 ± SD（截断纵轴）")
        _style(ax)
    axes[1].legend(frameon=False,bbox_to_anchor=(1.02,1),loc="upper left",fontsize=8)
    fig.suptitle("五类癌症的分类表现（逐轮 OOF）",fontsize=14,fontweight="bold")
    fig.text(.5,-.02,"误差线为20轮重复OOF的描述性SD，不是置信区间。",ha="center",fontsize=9)
    _tidy(fig,out,"05_各癌种Recall与F1")

    # 6. 相对A纠错/新增错误，事件数及去重患者数并列。
    methods=[s for s in SCHEMES if s!="model_A"]
    short_method_labels = {
        "model_B": "B：高方差+SVM",
        "model_C": "C：ANOVA+LR",
        "hard_vote": "等权硬投票",
        "fixed_disagreement": "固定分歧规则*",
        "learned_inner_oof": "内层规则学习",
        "conservative_fallback": "分歧触发+回退A",
    }
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
    x=np.arange(len(methods));w=.36
    for ax,unit,title in zip(axes,["events","patients"],["重复预测事件", "不同患者（sample ID去重）"]):
        correct=[];new=[]
        for s in methods:
            g=changes.loc[changes.scheme.eq(s)]
            if unit=="events": correct.append(int(g.change.eq("corrected").sum()));new.append(int(g.change.eq("new_error").sum()))
            else: correct.append(g.loc[g.change.eq("corrected"),"sample_id"].nunique());new.append(g.loc[g.change.eq("new_error"),"sample_id"].nunique())
        ax.bar(x-w/2,correct,w,label="纠正A错误",color="#4A956C")
        ax.bar(x+w/2,new,w,label="新增错误",color="#BF665F")
        ax.set(xticks=x,xticklabels=[short_method_labels[s] for s in methods],ylabel=unit,title=title)
        ax.tick_params(axis="x",rotation=25,labelsize=8);_style(ax)
    axes[0].legend(frameon=False)
    fig.suptitle("相对模型 A 的纠错与预测退化",fontsize=14,fontweight="bold")
    _tidy(fig,out,"06_纠错与新增错误")

    # 7. 每种模式在100个外层训练集中的规则选择频次。
    freq=rules.groupby(["pattern","selected_model"],as_index=False).size().pivot(index="pattern",columns="selected_model",values="size").reindex(PATTERNS).fillna(0)
    for m in "ABC":
        if m not in freq: freq[m]=0
    fig,ax=plt.subplots(figsize=(9.2,4.8),layout="constrained")
    bottom=np.zeros(len(PATTERNS))
    for m in "ABC":
        vals=freq[m].to_numpy()
        ax.bar(np.arange(5),vals,bottom=bottom,color=MEMBER_COLORS[m],label=f"采用模型 {m}",width=.68)
        bottom+=vals
    eligible=rules.groupby("pattern").eligible_to_override_A.sum().reindex(PATTERNS).fillna(0).astype(int)
    ax.set(xticks=np.arange(5),xticklabels=[f"{p}\n(通过门槛 {eligible.loc[p]}/100)" for p in PATTERNS],
           ylabel="外层训练折中选择次数（每模式最多100）",title="内层 OOF 学得的模式规则频率")
    ax.legend(frameon=False,ncol=3);_style(ax)
    fig.text(.5,-.01,"未达到≥10名不同训练患者且净纠错≥2时，规则回退模型A。",ha="center",fontsize=9)
    _tidy(fig,out,"07_仲裁规则选择频率")

    # 8. 触发率与相对A净减少错误的关系；不是独立性能关联检验。
    round_stats=rounds.groupby("scheme").agg(trigger_rate=("arbitration_trigger_rate","mean"),
            net=("n_net_errors_reduced_vs_A","mean"),macro_f1=("macro_f1","mean")).reindex(SCHEMES)
    fig,ax=plt.subplots(figsize=(9.3,5.2),layout="constrained")
    plotted = set()
    for s,row in round_stats.iterrows():
        point = (round(float(row.trigger_rate*100), 10), round(float(row.net), 10))
        if point in plotted:
            continue
        plotted.add(point)
        same = [name for name, other in round_stats.iterrows()
                if (round(float(other.trigger_rate*100), 10), round(float(other.net), 10)) == point]
        ax.scatter(point[0],point[1],s=75,color=COLORS[s],edgecolor="white",linewidth=.7,zorder=3)
        labels = [short_labels[name] for name in same]
        label = " / ".join(labels)
        ax.annotate(label,point,xytext=(8,8 if point[1] >= 0 else -15),textcoords="offset points",fontsize=8)
    ax.axhline(0,color="#555555",lw=.9,ls="--")
    ax.set(xlabel="20轮平均仲裁触发率（%验证事件）",ylabel="每轮相对模型A净减少错误事件（均值）",
           title="仲裁触发率与实际净错误变化")
    _style(ax)
    fig.text(.5,-.01,"y轴按640名患者的每轮OOF统计；同一患者跨轮重复，未作显著性检验。固定规则*为事后探索。",ha="center",fontsize=9)
    _tidy(fig,out,"08_触发率与净收益")


def main() -> None:
    """从已完成运行目录读取结果，单独重绘八张图，不重新拟合模型。"""
    parser = argparse.ArgumentParser(description="重绘动态仲裁实验图表（只读取已保存结果）")
    parser.add_argument("--run", required=True, help="动态仲裁实验运行目录")
    args = parser.parse_args()
    plot_all(Path(args.run))


if __name__ == "__main__":
    main()

