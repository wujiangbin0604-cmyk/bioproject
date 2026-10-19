# -*- coding: utf-8 -*-
"""独立核验开发集热图的全基因统计、Top50、Z-score、重合及样本隔离。"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from PIL import Image

from config import CLASS_ORDER, ExperimentConfig, PROJECT_DIR
from data_loader import DevelopmentData, load_existing_development_data, write_json


def verify(output: Path, data: DevelopmentData) -> dict:
    """按原始开发表达重新计算，不依赖生图模块的排名或标准化函数。"""
    checks = []

    def check(name, condition):
        if not bool(condition):
            raise AssertionError(f"热图验收失败：{name}")
        checks.append(name)

    def close(name, actual, expected, rtol=1e-9, atol=1e-10):
        check(name, np.allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True))

    summary = json.loads((output / "分析摘要.json").read_text(encoding="utf-8"))
    tables = output / "分析结果"
    matrix_dir, figures = tables / "绘图矩阵", output / "生成图片"
    manifest = json.loads((output / "split_manifest.json").read_text(encoding="utf-8"))
    # 完整排名存在几乎并列的浮点F值；使用往返精度，避免CSV默认解析改变末位。
    stats = pd.read_csv(tables / "全部基因统计与双排名.csv", float_precision="round_trip")
    order = pd.read_csv(tables / "患者显示顺序.csv")
    check("固定640×20531，ID及标签对齐", data.X.shape == (640, 20531) and data.X.index.equals(data.y.index))
    check("严格复用开发ID顺序，排除保留测试", data.X.index.tolist() == manifest["development_ids"]
          and not set(data.X.index) & set(manifest["reserved_test_ids"]))
    check("全基因原名称及顺序准确", stats.gene_id.tolist() == data.X.columns.tolist())
    expected_ids = [sid for label in CLASS_ORDER for sid in data.X.index[data.y.eq(label)]]
    check("患者顺序仅按预设癌种，组内保留原顺序", order.sample_id.tolist() == expected_ids)
    check("显示顺序表明确声明非聚类", order.order_is_prespecified.all() and not order.clustered.any())
    check("患者表无保留ID", not set(order.sample_id) & set(data.reserved_test_ids))
    values = data.X.to_numpy(dtype=float)
    means = values.mean(axis=0)
    variances = values.var(axis=0, ddof=1)
    total_ss = np.square(values - means).sum(axis=0)
    within_ss, between_ss = np.zeros(20531), np.zeros(20531)
    for label in CLASS_ORDER:
        group = values[data.y.eq(label).to_numpy()]
        group_mean = group.mean(axis=0)
        within_ss += np.square(group - group_mean).sum(axis=0)
        between_ss += len(group) * np.square(group_mean - means)
        close(f"复算20531个{label}均值", stats[f"mean_{label}"], group_mean)
        check(f"{label}样本量一致", summary["data"]["class_counts"][label] == len(group))
    close("全部基因跨640人方差ddof=1", stats.variance, variances)
    close("全部基因总体均值", stats.global_mean, means)
    close("全部基因总体标准差ddof=0", stats.global_std_ddof0, values.std(axis=0, ddof=0))
    close("组间平方和", stats.ss_between_classes, between_ss)
    close("组内平方和", stats.ss_within_classes, within_ss)
    close("总变异分解", total_ss, between_ss + within_ss)
    constant = np.ptp(values, axis=0) == 0
    with np.errstate(divide="ignore", invalid="ignore"):
        manual_f = (between_ss / 4) / (within_ss / 635)
        eta = between_ss / total_ss
    manual_f[constant] = np.nan
    eta[constant] = np.nan
    close("独立公式复算五分类ANOVA F-score", stats.anova_f_score, manual_f, rtol=1e-6, atol=1e-6)
    close("eta_squared复算", stats.eta_squared, eta)
    check("恒定基因F空值保留", stats.loc[constant, "anova_f_score"].isna().all()
          and summary["score_quality"]["n_constant_genes"] == int(constant.sum()))
    for method, scores, rank_col, filename in (
        ("variance", variances, "variance_rank", "基因跨样本方差排名.csv"),
        ("anova", stats.anova_f_score.to_numpy(), "anova_rank", "五分类ANOVA_Fscore排名.csv")):
        indices = np.argsort(-np.where(np.isnan(scores), -np.inf, scores), kind="stable")
        expected_rank = np.empty(20531, dtype=int)
        expected_rank[indices] = np.arange(1, 20532)
        close(f"{method}全部20531个排名", stats[rank_col], expected_rank)
        ranking = pd.read_csv(tables / filename)
        check(f"{method}完整排序CSV", ranking.gene_id.tolist() == data.X.columns[indices].tolist())
    tops = {}
    names = {"variance": ("方差Top50基因统计.csv", "01_方差Top50_患者级热图", "02_方差Top50_癌种均值热图", "05_方差Top50_癌种内差异补充热图"),
             "anova": ("ANOVA_Top50基因统计.csv", "03_ANOVA_Top50_患者级热图", "04_ANOVA_Top50_癌种均值热图", "06_ANOVA_Top50_癌种内差异补充热图")}
    variation = pd.read_csv(tables / "Top50组内个体差异统计.csv")
    for method in ("variance", "anova"):
        top = pd.read_csv(tables / names[method][0])
        genes = top.gene_id.tolist()
        tops[method] = set(genes)
        check(f"{method}恰好50个正确基因", len(genes) == len(set(genes)) == 50
              and genes == stats.sort_values(f"{method}_rank").head(50).gene_id.tolist())
        subset = data.X.loc[:, genes]
        array = subset.to_numpy(dtype=float)
        z = (array - array.mean(axis=0)) / array.std(axis=0, ddof=0)
        z_frame = pd.DataFrame(z, index=subset.index, columns=genes)
        patient = pd.read_csv(matrix_dir / f"{method}_患者级Zscore.csv", index_col=0)
        class_means = pd.read_csv(matrix_dir / f"{method}_癌种均值Zscore.csv", index_col=0)
        within = pd.read_csv(matrix_dir / f"{method}_癌种内Zscore.csv", index_col=0)
        check(f"{method}患者矩阵50×640且ID/基因顺序正确", patient.shape == (50, 640)
              and patient.index.tolist() == genes and patient.columns.tolist() == expected_ids)
        check(f"{method}均值矩阵50×5且顺序正确", class_means.shape == (50, 5)
              and class_means.index.tolist() == genes and class_means.columns.tolist() == list(CLASS_ORDER))
        close(f"{method}患者Z独立重算", patient, z_frame.loc[expected_ids].T)
        close(f"{method}640人逐基因Z均值0", patient.mean(axis=1), np.zeros(50))
        close(f"{method}640人逐基因Z标准差1", patient.std(axis=1, ddof=0), np.ones(50))
        for label in CLASS_ORDER:
            mask = data.y.eq(label)
            group_z = z_frame.loc[mask]
            close(f"{method}/{label}主图均值等于患者Z均值", class_means[label], group_z.mean(axis=0))
            group = subset.loc[mask]
            local = group.to_numpy(dtype=float)
            std = local.std(axis=0, ddof=0)
            stable = (local.max(axis=0) != local.min(axis=0)) & (std > 0)
            expected_within = (local - local.mean(axis=0)) / np.where(stable, std, 1.0)
            expected_within[:, ~stable] = 0.0
            close(f"{method}/{label}补充图癌种内Z复算", within.loc[genes, group.index].to_numpy(), expected_within.T)
            check(f"{method}/{label}全部患者显示而非组均值复制", len(group.index) == within.loc[:, group.index].shape[1])
            recorded_variation = variation.loc[variation.selection_method.eq(method) & variation.cancer_type.eq(label)].set_index("gene_id").loc[genes]
            close(f"{method}/{label}组内SD表复算", recorded_variation.global_z_std_within_class, group_z.std(axis=0, ddof=0))
        weighted = class_means.to_numpy() @ np.asarray([summary["data"]["class_counts"][c] for c in CLASS_ORDER]) / 640
        close(f"{method}类均值按实际样本数加权为0", weighted, np.zeros(50))
        for name in names[method][1:]:
            with Image.open(figures / f"{name}.png") as image:
                image.verify()
            with Image.open(figures / f"{name}.png") as image:
                check(f"{name}：高清PNG完整", min(image.info.get("dpi", (0, 0))) >= 300 and min(image.size) >= 2000)
            check(f"{name}：PDF存在", (figures / f"{name}.pdf").read_bytes().startswith(b"%PDF"))
    overlap = len(tops["variance"] & tops["anova"])
    union = len(tops["variance"] | tops["anova"])
    check("重合基因列表准确", set(pd.read_csv(tables / "两种Top50重合基因.csv").gene_id) == tops["variance"] & tops["anova"])
    check("两组重合数及并集数准确", summary["overlap"]["overlap_count"] == overlap and summary["overlap"]["union_count"] == union)
    close("Jaccard按交集/并集重算", summary["overlap"]["jaccard"], overlap / union)
    saved_overlap = pd.read_csv(tables / "Top50重合与Jaccard.csv").iloc[0]
    close("Jaccard CSV准确", saved_overlap.jaccard, overlap / union)
    scope = summary["analysis_scope"]
    check("未启动RQ1、分类训练、CV或测试评估", all(scope[k] is False for k in (
        "rq1_model_training_started", "cross_validation_started", "classifier_fit_performed", "test_evaluation_performed", "usable_as_fixed_features_for_later_cv")))
    check("未聚类、未根据PCA/显著性选择", summary["methods"]["clustering_performed"] is False
          and summary["methods"]["p_value_based_selection"] is False and summary["methods"]["pca_based_selection"] is False)
    for relative, expected in summary["protected_file_sha256_before"].items():
        current = hashlib.sha256((PROJECT_DIR / relative).read_bytes()).hexdigest()
        check(f"固定清单及模型文件未改动：{relative}", current == expected == summary["protected_file_sha256_after"][relative])
    report = {"passed": True, "n_checks": len(checks), "checks": checks, "n_classifier_fits": 0,
              "reserved_values_used_in_statistics_or_figures": False,
              "n_main_png": 4, "n_supplementary_png": 2, "n_pdf": 6}
    write_json(output / "verification.json", report)
    print(f"开发集热图验收通过：{len(checks)}项；未拟合分类器、未使用测试表达/标签。", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    cfg = ExperimentConfig()
    output_dir = args.run_dir.resolve() if args.run_dir else cfg.output_dir / json.loads(
        (cfg.output_dir / "latest_development_heatmaps.json").read_text(encoding="utf-8"))["run_directory"]
    source = json.loads((output_dir / "development_data_record.json").read_text(encoding="utf-8"))["source"]
    if source["format"] == "tar":
        cfg = replace(cfg, raw_archive=Path(source["archive"]))
    else:
        cfg = replace(cfg, data_dir=Path(source["data"]).parent)
    with TemporaryDirectory(prefix="heatmap_verify_", dir=cfg.output_dir) as temporary:
        development = load_existing_development_data(cfg, Path(temporary))
        verify(output_dir, development)
