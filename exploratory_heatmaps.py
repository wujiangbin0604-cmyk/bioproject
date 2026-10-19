# -*- coding: utf-8 -*-
"""仅开发集的方差/ANOVA Top50探索热图；不执行CV或分类器拟合。"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.feature_selection import f_classif
from threadpoolctl import threadpool_limits

from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from data_loader import DevelopmentData, load_existing_development_data, write_json
from visualization import configure_fonts


CLASS_COLORS = {"BRCA": "#3D6FA5", "KIRC": "#2B9A85", "COAD": "#D08A31",
                "LUAD": "#C45A65", "PRAD": "#8068A8"}
TOP_K = 50
COLOR_LIMIT = 3.0
FIGURES = {
    "variance": ("01_方差Top50_患者级热图", "02_方差Top50_癌种均值热图", "05_方差Top50_癌种内差异补充热图"),
    "anova": ("03_ANOVA_Top50_患者级热图", "04_ANOVA_Top50_癌种均值热图", "06_ANOVA_Top50_癌种内差异补充热图"),
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rank_development_genes(data: DevelopmentData) -> tuple[pd.DataFrame, dict]:
    """方差在原表达尺度计算(ddof=1)；F-score是五分类组间/组内均方比。

    恒定基因的F未定义，保留NaN并置于排名末尾，不能当作真实F=0。
    排名并列时按原基因列顺序决定；不使用PCA或已计算的全样本排名。
    """
    X, y = data.X, data.y
    values = X.to_numpy(dtype=np.float64)
    means = values.mean(axis=0)
    variance = values.var(axis=0, ddof=1)
    constant = np.ptp(values, axis=0) == 0
    ssw, ssb = np.zeros(X.shape[1]), np.zeros(X.shape[1])
    class_means = {}
    for label in CLASS_ORDER:
        group = values[y.eq(label).to_numpy()]
        group_mean = group.mean(axis=0)
        class_means[label] = group_mean
        ssw += np.square(group - group_mean).sum(axis=0)
        ssb += len(group) * np.square(group_mean - means)
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
        warnings.simplefilter("always")
        f_scores, _ = f_classif(X, y)
    f_scores = np.asarray(f_scores, dtype=float)
    f_scores[constant] = np.nan
    if np.isnan(f_scores[~constant]).any() or (f_scores[~constant] < 0).any():
        raise ValueError("非恒定基因出现未定义或负ANOVA F值，需要检查真实数据和数值精度")
    with np.errstate(divide="ignore", invalid="ignore"):
        manual_f = (ssb / (len(CLASS_ORDER) - 1)) / (ssw / (len(X) - len(CLASS_ORDER)))
        eta_squared = ssb / ((len(X) - 1) * variance)
    eligible = ~constant & np.isfinite(f_scores) & np.isfinite(manual_f)
    np.testing.assert_allclose(f_scores[eligible], manual_f[eligible], rtol=1e-6, atol=1e-6)
    eta_squared[constant] = np.nan
    variance_order = np.argsort(-variance, kind="stable")
    anova_order = np.argsort(-np.where(np.isnan(f_scores), -np.inf, f_scores), kind="stable")
    variance_rank = np.empty(X.shape[1], dtype=int)
    anova_rank = np.empty(X.shape[1], dtype=int)
    variance_rank[variance_order] = np.arange(1, X.shape[1] + 1)
    anova_rank[anova_order] = np.arange(1, X.shape[1] + 1)
    state = np.where(constant, "constant_undefined_F", np.where(np.isposinf(f_scores), "infinite_F", "finite_F"))
    stats = pd.DataFrame({"gene_id": X.columns, "variance": variance, "variance_rank": variance_rank,
                          "anova_f_score": f_scores, "anova_rank": anova_rank, "anova_status": state,
                          "global_mean": means, "global_std_ddof0": values.std(axis=0, ddof=0),
                          "ss_between_classes": ssb, "ss_within_classes": ssw, "eta_squared": eta_squared,
                          **{f"mean_{label}": class_means[label] for label in CLASS_ORDER}})
    stats["in_variance_top50"] = stats.variance_rank.le(TOP_K)
    stats["in_anova_top50"] = stats.anova_rank.le(TOP_K) & ~constant
    info = {"n_constant_genes": int(constant.sum()), "n_undefined_anova_f": int(np.isnan(f_scores).sum()),
            "n_infinite_anova_f": int(np.isposinf(f_scores).sum()),
            "f_score_crosscheck_max_abs_error": float(np.max(np.abs(f_scores[eligible] - manual_f[eligible]))),
            "f_score_crosscheck_passed": True,
            "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught]}
    return stats, info


def display_order(data: DevelopmentData) -> tuple[list[str], pd.DataFrame]:
    """仅按预设癌种顺序稳定排序；组内保留已固定开发集顺序。"""
    ids, rows = [], []
    original_positions = {sid: i + 1 for i, sid in enumerate(data.X.index)}
    for label in CLASS_ORDER:
        for within_position, sid in enumerate(data.y.index[data.y.eq(label)], start=1):
            ids.append(sid)
            rows.append({"display_column": len(ids), "sample_id": sid, "cancer_type": label,
                         "within_class_position": within_position, "original_development_position": original_positions[sid],
                         "order_is_prespecified": True, "clustered": False})
    if len(ids) != 640 or len(set(ids)) != 640 or set(ids) & set(data.reserved_test_ids):
        raise AssertionError("热图患者列未严格限制为640个开发ID")
    return ids, pd.DataFrame(rows)


def make_heatmap_matrices(data: DevelopmentData, genes: list[str], ids: list[str]) -> dict:
    """主图使用640人逐基因Z；补充图另用癌种内均值和标准差(ddof=0)。"""
    selected = data.X.loc[:, genes]
    global_mean, global_std = selected.mean(axis=0), selected.std(axis=0, ddof=0)
    if not global_std.gt(0).all():
        raise ValueError("Top50含零方差基因，不能作逐基因Z标准化")
    z = selected.sub(global_mean, axis=1).div(global_std, axis=1)
    z_class = pd.DataFrame({label: z.loc[data.y.eq(label)].mean(axis=0) for label in CLASS_ORDER})
    within = pd.DataFrame(index=selected.index, columns=genes, dtype=float)
    variation_rows = []
    zero_within = 0
    for label in CLASS_ORDER:
        mask = data.y.eq(label)
        group, z_group = selected.loc[mask], z.loc[mask]
        local_mean, local_std = group.mean(axis=0), group.std(axis=0, ddof=0)
        stable = local_std.gt(0) & group.max(axis=0).ne(group.min(axis=0))
        local_z = group.sub(local_mean, axis=1).div(local_std.where(stable, 1.0), axis=1)
        local_z.loc[:, ~stable] = 0.0
        zero_within += int((~stable).sum())
        within.loc[mask, :] = local_z.to_numpy()
        for gene in genes:
            variation_rows.append({"gene_id": gene, "cancer_type": label, "n_samples": int(mask.sum()),
                                   "raw_mean": float(local_mean[gene]), "raw_std_ddof0": float(local_std[gene]),
                                   "global_z_std_within_class": float(z_group[gene].std(ddof=0)),
                                   "global_z_IQR_within_class": float(z_group[gene].quantile(.75) - z_group[gene].quantile(.25)),
                                   "constant_within_class": bool(not stable[gene])})
    return {"patient": z.loc[ids].T.rename_axis("gene_id"), "class_mean": z_class.rename_axis("gene_id"),
            "within_class": within.loc[ids].T.rename_axis("gene_id"),
            "variation": pd.DataFrame(variation_rows), "constant_within_class_gene_pairs": zero_within}


def _save_heatmap(matrix: pd.DataFrame, labels: list[str], counts: dict, output: Path,
                  name: str, title: str, *, mean_map: bool = False, within: bool = False) -> dict:
    """逐格绘制且不平滑；PDF保留单元格、文字和色条矢量对象。"""
    configure_fonts()
    fig = plt.figure(figsize=(8.8 if mean_map else 18.0, 11.8), facecolor="white")
    left, width = (.23, .54) if mean_map else (.105, .77)
    ax = fig.add_axes([left, .12, width, .72])
    array = matrix.to_numpy(dtype=float)
    mesh = ax.pcolormesh(np.arange(matrix.shape[1] + 1), np.arange(matrix.shape[0] + 1), array,
                         cmap="RdBu_r", norm=Normalize(-COLOR_LIMIT, COLOR_LIMIT), shading="flat",
                         edgecolors="none", linewidth=0, antialiased=False, rasterized=False)
    ax.set(xlim=(0, matrix.shape[1]), ylim=(matrix.shape[0], 0), ylabel="基因（按本方法分数降序）")
    ax.set_yticks(np.arange(len(matrix)) + .5, matrix.index, fontsize=8)
    ax.tick_params(axis="y", length=0, pad=5)
    for spine in ax.spines.values():
        spine.set_visible(False)
    strip = fig.add_axes([left, .857, width, .017], sharex=ax)
    offset = 0
    for i, label in enumerate(CLASS_ORDER):
        block_width = 1 if mean_map else counts[label]
        strip.add_patch(Rectangle((offset, 0), block_width, 1, color=CLASS_COLORS[label], lw=0))
        strip.text(offset + block_width / 2, 1.35, f"{label}\n(n={counts[label]})", ha="center", va="bottom", fontsize=8.5)
        if offset:
            ax.axvline(offset, color="#333333", linewidth=.8)
        offset += block_width
    strip.set(ylim=(0, 1))
    strip.set_axis_off()
    if mean_map:
        ax.set_xticks(np.arange(5) + .5, CLASS_ORDER, fontsize=9)
        ax.set_xlabel("癌种（各列等宽；样本量见顶部）", labelpad=10)
        for row in range(matrix.shape[0]):
            for col in range(5):
                value = array[row, col]
                ax.text(col + .5, row + .5, f"{value:.2f}", ha="center", va="center", fontsize=7.7,
                        color="white" if abs(value) >= 1.7 else "#222222")
    else:
        positions = [1, 100, 200, 300, 400, 500, 600, 640]
        ax.set_xticks(np.asarray(positions) - .5, positions, fontsize=9)
        ax.set_xlabel("患者样本（显示列序号；完整样本ID另存CSV）", labelpad=10)
    cax = fig.add_axes([left + width + .035, .27, .018 if mean_map else .012, .43])
    colorbar = fig.colorbar(mesh, cax=cax, extend="both", ticks=[-3, -2, -1, 0, 1, 2, 3])
    scale = "癌种内逐基因 Z-score" if within else ("患者 Z-score 的癌种均值" if mean_map else "逐基因 Z-score（640人）")
    colorbar.set_label(scale, labelpad=10, fontsize=10)
    fig.text(.5, .967, title, ha="center", va="top", fontsize=14)
    subtitle = "癌种顺序为预设顺序，非聚类结果"
    if within:
        subtitle += "；补充图使用癌种内标准化"
    elif mean_map:
        subtitle += "；对640人Z-score按癌种取均值"
    else:
        subtitle += "；组内保留原开发集顺序"
    fig.text(.5, .931, subtitle, ha="center", va="top", fontsize=9.5)
    footer = "仅640个开发样本；排除161个保留样本。颜色范围统一为[−3, 3]，超出范围仅颜色饱和，CSV保留完整数值。"
    interpretation = ("补充图：(表达值−该癌种该基因均值)/该癌种该基因标准差；放大组内相对差异，不能用于比较癌种均值。"
                      if within else "主图：(表达值−该基因640人均值)/该基因640人标准差；蓝/白/红代表相对低/平均/高，不代表绝对表达量。")
    fig.text(.5, .047, footer + "\n" + interpretation, ha="center", va="center", fontsize=8 if mean_map else 9, linespacing=1.7)
    output.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig.savefig(output / f"{name}.png", dpi=330, bbox_inches="tight", pad_inches=.18)
        fig.savefig(output / f"{name}.pdf", bbox_inches="tight", pad_inches=.18)
    plt.close(fig)
    if any("Glyph" in str(w.message) and "missing" in str(w.message) for w in caught):
        raise RuntimeError("图中文字存在缺失字体，已停止验收")
    return {"name": name, "n_genes": len(matrix), "n_columns": matrix.shape[1], "scale": scale,
            "values_outside_color_limits": int((np.abs(array) > COLOR_LIMIT).sum()),
            "fraction_outside_color_limits": float((np.abs(array) > COLOR_LIMIT).mean()),
            "png_dpi": 330, "prespecified_order_not_clustering": True,
            "warnings": [str(w.message) for w in caught]}


def run(cfg: ExperimentConfig) -> Path:
    """新建独立EDA输出；不改变原数据、固定划分、既有模型实验及其指针。"""
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    output = cfg.output_dir / "development_heatmaps" / stamp
    output.mkdir(parents=True, exist_ok=False)
    tables, matrices_dir, figures = output / "分析结果", output / "分析结果" / "绘图矩阵", output / "生成图片"
    matrices_dir.mkdir(parents=True)
    start = time.perf_counter()
    status = {"status": "running", "analysis": "development_only_exploratory_heatmaps",
              "rq1_model_training_started": False, "cross_validation_started": False,
              "classifier_fit_performed": False, "test_evaluation_performed": False,
              "exploratory_anova_scope": "all_fixed_640_development_samples_only",
              "usable_as_fixed_features_for_later_cv": False}
    write_json(output / "stage_status.json", status)
    protected = [cfg.split_manifest_path, PROJECT_DIR / "main.py", PROJECT_DIR / "feature_selection.py"]
    before_hash = {str(p.relative_to(PROJECT_DIR)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    try:
        print("读取已确定的640人开发集，排除保留测试样本...", flush=True)
        data = load_existing_development_data(cfg, output)
        record = _json(output / "development_data_record.json")
        previous_pointer = cfg.output_dir / "latest_repeated_cv.json"
        if previous_pointer.exists():
            previous = cfg.output_dir / _json(previous_pointer)["run_directory"]
            previous_record = _json(previous / "development_data_record.json")
            if record["development_fingerprint_sha256"] != previous_record["development_fingerprint_sha256"]:
                raise ValueError("开发集表达/标签指纹与既有重复CV不同")
        print("计算20531个基因方差、五分类F-score和类均值...", flush=True)
        stats, score_info = rank_development_genes(data)
        ids, order_table = display_order(data)
        counts = {c: int(data.y.eq(c).sum()) for c in CLASS_ORDER}
        top_variance = stats.sort_values("variance_rank").head(TOP_K)
        top_anova = stats.sort_values("anova_rank").head(TOP_K)
        if top_anova.anova_f_score.isna().any():
            raise ValueError("不足50个可计算ANOVA的基因")
        common = set(top_variance.gene_id) & set(top_anova.gene_id)
        union = set(top_variance.gene_id) | set(top_anova.gene_id)
        overlap = {"variance_top_k": TOP_K, "anova_top_k": TOP_K, "overlap_count": len(common),
                   "union_count": len(union), "jaccard": len(common) / len(union)}
        for table, name in ((stats, "全部基因统计与双排名"),
                            (stats.sort_values("variance_rank"), "基因跨样本方差排名"),
                            (stats.sort_values("anova_rank"), "五分类ANOVA_Fscore排名"),
                            (top_variance, "方差Top50基因统计"), (top_anova, "ANOVA_Top50基因统计"),
                            (stats.loc[stats.gene_id.isin(common)].sort_values("variance_rank"), "两种Top50重合基因"),
                            (order_table, "患者显示顺序"), (pd.DataFrame([overlap]), "Top50重合与Jaccard")):
            table.to_csv(tables / f"{name}.csv", index=False, encoding="utf-8-sig")
        results, variation_tables, plot_records, top_info = {}, [], [], {}
        for method, top, text in (("variance", top_variance, "方差"), ("anova", top_anova, "ANOVA F-score")):
            genes = top.gene_id.tolist()
            result = make_heatmap_matrices(data, genes, ids)
            results[method] = result
            for key, title in (("patient", "患者级Zscore"), ("class_mean", "癌种均值Zscore"), ("within_class", "癌种内Zscore")):
                result[key].to_csv(matrices_dir / f"{method}_{title}.csv", encoding="utf-8-sig")
            variation_tables.append(result["variation"].assign(selection_method=method))
            stems = FIGURES[method]
            print(f"绘制{text} Top50：患者级、癌种均值和癌种内差异补充图...", flush=True)
            plot_records.append(_save_heatmap(result["patient"], ids, counts, figures, stems[0],
                                               f"开发集{text} Top50 基因：患者级表达热图"))
            plot_records.append(_save_heatmap(result["class_mean"], list(CLASS_ORDER), counts, figures, stems[1],
                                               f"开发集{text} Top50 基因：癌种均值热图", mean_map=True))
            plot_records.append(_save_heatmap(result["within_class"], ids, counts, figures, stems[2],
                                               f"开发集{text} Top50 基因：癌种内个体差异", within=True))
            top_info[method] = {"top_genes": genes, "median_eta_squared": float(top.eta_squared.median()),
                                "median_within_class_sd_on_global_z_scale": float(result["variation"].global_z_std_within_class.median()),
                                "constant_within_class_gene_pairs": result["constant_within_class_gene_pairs"]}
        pd.concat(variation_tables, ignore_index=True).to_csv(tables / "Top50组内个体差异统计.csv", index=False, encoding="utf-8-sig")
        after_hash = {str(p.relative_to(PROJECT_DIR)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        if before_hash != after_hash:
            raise AssertionError("固定清单或模型模块被意外修改")
        summary = {"data": {"n_development": 640, "n_genes": 20531, "n_reserved_excluded": 161,
                             "class_counts": counts, "development_fingerprint_sha256": record["development_fingerprint_sha256"]},
                   "analysis_scope": {k: v for k, v in status.items() if k != "status"}, "overlap": overlap, "score_quality": score_info,
                   "top50_descriptive_results": top_info, "figures": plot_records,
                   "methods": {"variance_ddof": 1, "zscore_ddof": 0, "anova": "sklearn.feature_selection.f_classif",
                               "anova_degrees_of_freedom": [4, 635], "class_order": list(CLASS_ORDER),
                               "within_class_order": "original_fixed_development_order", "clustering_performed": False,
                               "tie_break": "original_gene_column_order", "mean_map": "class_mean_of_640_patient_gene_Z",
                               "color_limits": [-3, 3], "saturation_does_not_change_saved_values": True,
                               "p_value_based_selection": False, "pca_based_selection": False},
                   "protected_file_sha256_before": before_hash, "protected_file_sha256_after": after_hash,
                   "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                                   "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                                   "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
                   "elapsed_seconds": time.perf_counter() - start}
        write_json(output / "分析摘要.json", summary)
        write_json(output / "warnings.json", {"warnings": score_info["warnings"]})
        _write_report(output, summary, top_variance, top_anova)
        # 独立验收使用同一原始开发矩阵，另按公式复算；不会读取测试表达或训练分类器。
        from verify_development_heatmaps import verify
        verify(output, data=data)
        source_dir = output / "source_snapshot"
        source_dir.mkdir()
        for file in (Path(__file__), PROJECT_DIR / "verify_development_heatmaps.py", PROJECT_DIR / "data_loader.py",
                     PROJECT_DIR / "config.py", PROJECT_DIR / "visualization.py"):
            (source_dir / file.name).write_bytes(file.read_bytes())
        status.update(status="complete", elapsed_seconds=time.perf_counter() - start)
        write_json(output / "stage_status.json", status)
        write_json(cfg.output_dir / "latest_development_heatmaps.json", {"run_directory": str(output.relative_to(cfg.output_dir)), "status": "complete"})
        print(f"完成：重合{len(common)}个，Jaccard={overlap['jaccard']:.8f}；结果：{output}", flush=True)
        return output
    except Exception as exc:
        status.update(status="failed", error=str(exc))
        write_json(output / "stage_status.json", status)
        (output / "error_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


def _write_report(output: Path, summary: dict, variance: pd.DataFrame, anova: pd.DataFrame) -> None:
    """只在真实计算后填入数值，明确选择偏倚、图像含义和正式CV边界。"""
    overlap, info = summary["overlap"], summary["top50_descriptive_results"]
    report = ["# 固定640人开发集：方差与ANOVA Top50探索性热图", "",
              "## 输入与数据隔离", "",
              "按已保存清单复用640个开发样本和原始20,531个gene_*表达列；不重新train_test_split，不使用161个保留测试样本计算排名、均值、标准差或作图。",
              f"开发类别计数：{summary['data']['class_counts']}。与既有重复CV开发集指纹一致。",
              "原TAR/CSV物理上含801行，读取后立即截取固定开发行；仅使用保留ID核对隔离。原CSV、固定划分及模型代码未修改。", "",
              "## 排名与重合", "",
              "方差在提供的原表达尺度上、跨640人计算，ddof=1，未先标准化。ANOVA使用f_classif和五类真实开发标签，F=(SS_between/4)/(SS_within/635)。两者并列时按原基因列顺序排序。",
              f"恒定基因{summary['score_quality']['n_constant_genes']}个，其F未定义，CSV保留空值并放于F排名末尾；不伪造F=0。",
              f"两种Top50重合 **{overlap['overlap_count']}** 个，合并 **{overlap['union_count']}** 个，Jaccard=交集/并集=**{overlap['jaccard']:.8f}**。",
              "这是两个筛选准则在同一开发集上的集合一致性，不是重复子采样的特征选择稳定性，也不证明分类性能。",
              f"方差第1名：{variance.iloc[0].gene_id}，方差={variance.iloc[0].variance:.6f}，F={variance.iloc[0].anova_f_score:.6f}。",
              f"ANOVA第1名：{anova.iloc[0].gene_id}，F={anova.iloc[0].anova_f_score:.6f}，方差={anova.iloc[0].variance:.6f}。", "",
              "## 四张主图", "",
              "01/03是患者级热图：每格为一个基因在一个开发样本的Z=(x−该基因640人均值)/该基因640人标准差(ddof=0)。未抽样、未平均患者、未插值平滑，640列均显示。",
              "列按预设BRCA→KIRC→COAD→LUAD→PRAD排序，组内保留固定开发名单顺序；这不是聚类结果。行按各自方差或F排名降序，无基因聚类。",
              "02/04是癌种均值热图：对上述患者Z按癌种求均值，等价于(该类原表达均值−640人基因均值)/640人基因标准差；没有对五个均值再次Z标准化。",
              "主图共享同一基因的标准化基准和[−3,3]色标；蓝白红表示相对低、平均、高，不能解释为绝对表达量。癌种均值列等宽，不代表样本数量相同，实际n标在顶部。",
              "颜色饱和仅影响显示，完整未裁剪数值保存于绘图矩阵CSV。每图具体饱和数量见分析摘要.json。", "",
              "## 组内个体差异补充图", "",
              "05/06仍保留各自相同Top50和全部640列，但用每个癌种内部的基因均值和标准差计算Z。其作用是放大同癌种个体相对偏离，不能与主图数值混用或比较癌种绝对均值。",
              "癌种内恒定基因显示Z=0并在组内差异CSV标记；标准差很小时，这种标准化也可能放大小幅变化或技术噪声。",
              f"在主图Z尺度，方差Top50的250个基因×癌种组合的组内SD中位数={info['variance']['median_within_class_sd_on_global_z_scale']:.6f}；ANOVA Top50为{info['anova']['median_within_class_sd_on_global_z_scale']:.6f}。",
              f"跨五类均值解释总变异比例η²的基因中位数：方差Top50={info['variance']['median_eta_squared']:.6f}，ANOVA Top50={info['anova']['median_eta_squared']:.6f}。",
              "这些是已选基因的描述统计：ANOVA直接偏向组间差异大、组内差异小的基因，所以图中类间分块清晰不能作为独立验证。组均值图会掩盖个体异质性，应结合患者图、补充图和组内SD/IQR表阅读。", "",
              "## 后续建模限制", "",
              "**禁止把本次全640人探索得到的Top50作为之后交叉验证的固定基因集合。** 虽然161例被隔离，但这些基因已利用未来CV验证折的标签；预先固定会造成开发CV泄漏。",
              "正式CV仍须每个训练折内部重新拟合SelectKBest(f_classif)→StandardScaler→分类器，并仅用训练折所选基因变换验证折。K和C的模型选择也只能在规定开发流程内进行。",
              "本次不训练分类器、不启动RQ1、不执行交叉验证、不评估测试集，也不更新原基线/重复CV指针。",
              "F是单变量探索排名，不是PCA贡献度，不以p值或多重校正显著性选这50个基因。ANOVA等方差/独立性等假设及组织、平台、批次混杂限制了生物学解释；不将其称为关键致癌基因或因果标志物。",
              "低方差也不意味着没有生物学价值；这些图不能证明少量基因能达到全特征分类表现，RQ1仍待正式折内实验。", "",
              "## 复现", "", "在项目根目录运行：", "", "```powershell", "python exploratory_heatmaps.py",
              "python verify_development_heatmaps.py", "```", "",
              "实际依赖版本见分析摘要.json。没有随机抽样、聚类或随机模型拟合；固定开发集名单来自种子42的既有划分。",
              "复核完整F排名时用pd.read_csv(..., float_precision='round_trip')读取CSV，避免默认浮点解析改变几乎并列分数的末位。排序依据是未四舍五入的分数，不能按图中或打印的少量小数位重排。",
              "方法参考：[scikit-learn f_classif](https://scikit-learn.org/stable/modules/generated/sklearn.feature_selection.f_classif.html)、[SciPy Z-score定义](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.zscore.html)。"]
    (output / "开发集热图分析说明.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    config = ExperimentConfig()
    if args.archive:
        config = replace(config, raw_archive=args.archive.resolve())
    if args.data_dir:
        config = replace(config, data_dir=args.data_dir.resolve())
    try:
        run(config)
    except Exception as error:
        print(f"开发集探索热图失败：{error}", file=sys.stderr)
        raise SystemExit(1)
