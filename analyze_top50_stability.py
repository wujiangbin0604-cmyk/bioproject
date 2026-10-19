# -*- coding: utf-8 -*-
"""只分析既有Top50记录；不加载表达矩阵、不调用模型或特征评分函数。"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import platform
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from config import ExperimentConfig, PROJECT_DIR
from visualization import configure_fonts, _save

METHODS = ("anova_top50_svm", "variance_top50_svm")
NAMES = {METHODS[0]: "ANOVA Top50", METHODS[1]: "高方差 Top50"}
COLORS = {METHODS[0]: "#C45A65", METHODS[1]: "#38898C"}
KEYS = ["repeat_id", "fold_id"]


def json_read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def describe(array):
    """高度相关的比较值仅作描述，样本标准差使用ddof=1。"""
    a = np.asarray(array, dtype=float)
    if not len(a) or not np.isfinite(a).all():
        raise ValueError("描述统计存在空输入或非有限值")
    return {"n_comparisons": len(a), "mean": float(a.mean()), "sample_std": float(a.std(ddof=1)),
            "min": float(a.min()), "max": float(a.max()), "median": float(np.median(a)),
            "p05": float(np.quantile(a, .05)), "p25": float(np.quantile(a, .25)),
            "p75": float(np.quantile(a, .75)), "p95": float(np.quantile(a, .95))}


def normalize_keys(frame):
    """只适配已经明确的round/repeat与fold字段，若记录冲突就停止。"""
    table = frame.copy()
    for canonical, aliases in (("repeat_id", ("repeat_id", "repeat", "round")),
                                ("fold_id", ("fold_id", "fold"))):
        found = [name for name in aliases if name in table]
        if not found:
            raise ValueError(f"缺少{canonical}，实际列：{list(table.columns)}")
        values = pd.to_numeric(table[found[0]], errors="raise")
        if values.isna().any() or not np.equal(values, np.floor(values)).all():
            raise ValueError(f"{canonical}不是完整整数")
        for name in found[1:]:
            if not values.equals(pd.to_numeric(table[name], errors="raise")):
                raise ValueError(f"{canonical}的多种字段记录相互矛盾")
        table[canonical] = values.astype(int)
    if not table.repeat_id.between(1, 20).all() or not table.fold_id.between(1, 5).all():
        raise ValueError("训练折编号不属于预期20轮×5折")
    expected = (table.repeat_id - 1) * 5 + table.fold_id
    if "evaluation_id" in table and not np.array_equal(table.evaluation_id, expected):
        raise ValueError("evaluation_id与repeat/fold映射不一致")
    table["evaluation_id"] = expected
    return table


def plot_results(output, within, between, frequencies, frequency_methods):
    """所有频率和Jaccard直接来自既有集合，绘图无随机抽样。"""
    font = configure_fonts()
    fig, axes = plt.subplots(1, 2, figsize=(11.7, 5.1), layout="constrained")
    bins = np.linspace(0, 1, 51)
    for method in METHODS:
        scores = within.loc[within.method.eq(method), "jaccard"]
        axes[0].hist(scores, bins=bins, histtype="step", lw=2, color=COLORS[method],
                     label=f"{NAMES[method]}：均值 {scores.mean():.5f}")
        ordered = np.sort(scores)
        axes[1].plot(ordered, np.arange(1, len(ordered) + 1) / len(ordered), color=COLORS[method],
                     lw=1.8, label=NAMES[method])
    axes[0].set(xlim=(0, 1), xlabel="同一方法、不同训练折集合的 Jaccard", ylabel="训练折集合对数量",
                title="两两 Jaccard 分布（每方法4950对）")
    axes[1].set(xlim=(0, 1), ylim=(0, 1.02), xlabel="两两 Jaccard", ylabel="累计比例",
                title="经验累积分布（保留所有训练折记录）")
    for ax in axes:
        ax.grid(axis="y", color="#E5E8EC")
        ax.legend(frameon=False, fontsize=8.5)
    fig.suptitle("Top50 基因集合的跨训练折一致性\n4950对共享特征集合且训练样本重叠，仅作描述，不视为独立实验", fontsize=12.5)
    _save(fig, output, "jaccard_stability_comparison")

    fig, axes = plt.subplots(1, 2, figsize=(11.7, 5.1), layout="constrained")
    counts = between.overlap_count.value_counts().sort_index()
    x = counts.index.to_numpy()
    js = x / (100 - x)
    axes[0].bar(js, counts.to_numpy(), width=.009, color="#8068A8", edgecolor="white")
    axes[0].axvline(between.jaccard.mean(), color="#333333", ls="--", lw=1,
                    label=f"平均 Jaccard={between.jaccard.mean():.5f}")
    for pos, count in zip(js, counts):
        axes[0].text(pos, count + .6, str(count), ha="center", fontsize=9)
    axes[0].set(xlim=(0, .3), xlabel="同轮、同折 ANOVA vs 高方差 Jaccard", ylabel="配对训练折数量",
                title="方法间同折Jaccard分布（100次）")
    axes[0].legend(frameon=False)
    axes[1].bar(x, counts, color="#6E8F9A", width=.7)
    for pos, count in counts.items():
        axes[1].text(pos, count + .6, str(count), ha="center", fontsize=9)
    axes[1].set(xlabel="每折两种Top50的重合基因数", ylabel="配对训练折数量", xticks=x,
                title=f"平均重合 {between.overlap_count.mean():.2f}/50；J=重合数/(100−重合数)")
    for ax in axes:
        ax.set_ylim(0, max(counts.max() * 1.18, 1))
        ax.grid(axis="y", color="#E5E8EC")
        ax.set_axisbelow(True)
    fig.suptitle("两种筛选方法的同折集合重合程度\n严格按 repeat_id、fold_id 一一配对，未比较两种方法的不同折", fontsize=12.5)
    _save(fig, output, "jaccard_between_methods")

    fig, axes = plt.subplots(1, 2, figsize=(12, 8.2), layout="constrained")
    top20_tables = []
    for ax, method in zip(axes, METHODS):
        top = frequencies.loc[frequencies.method.eq(method)].sort_values("frequency_display_rank").head(20)
        top20_tables.append(top)
        y = np.arange(20)
        ax.barh(y, top.selection_frequency * 100, color=COLORS[method], height=.7)
        ax.set(yticks=y, yticklabels=top.gene_id, xlabel="在100个训练折中的入选频率（%）", xlim=(0, 114),
               xticks=[0, 25, 50, 75, 100])
        ax.invert_yaxis()
        for pos, count, freq in zip(y, top.selected_fold_count, top.selection_frequency):
            ax.text(freq * 100 + 1.4, pos, f"{int(count)}/100", va="center", fontsize=8.5)
        always = frequency_methods.loc[frequency_methods.method.eq(method), "n_genes_selected_all_100"].iloc[0]
        ax.set_title(f"{NAMES[method]}：入选频率Top20\n共{int(always)}个基因在100折中始终入选", fontsize=11)
        ax.grid(axis="x", color="#E5E8EC")
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", labelsize=9)
    fig.suptitle("两种方法的高频入选基因\n同频按原始基因列序展示；本次Top20全部并列100%，顺序不代表重要性", fontsize=12.5)
    _save(fig, output, "feature_selection_frequency_top20")
    pd.concat(top20_tables).to_csv(output / "feature_selection_frequency_top20.csv", index=False, encoding="utf-8-sig")
    return font


def analyze(source, catalog_path, results_dir):
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    output = results_dir / "jaccard_analysis" / stamp
    output.mkdir(parents=True, exist_ok=False)
    checks, input_records = [], []

    def check(name, condition):
        if not bool(condition):
            raise ValueError(f"检查失败：{name}；不构造或补齐缺失集合")
        checks.append(name)

    def read(path, **kwargs):
        if not path.is_file():
            raise FileNotFoundError(f"缺少已保存记录：{path}；不能推测缺失内容")
        content = path.read_bytes()
        input_records.append({"path": str(path), "sha256": hashlib.sha256(content).hexdigest()})
        return pd.read_csv(path, float_precision="round_trip", **kwargs)

    def save(table, name):
        table.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")

    try:
        selected_path = source / "top50_selected_features_by_fold.csv"
        # 只读取集合与编号字段；不使用旧F-score或旧方差列，也不重新计算它们。
        selected = normalize_keys(read(selected_path, usecols=lambda c: c in {
            "method", "evaluation_id", "round", "repeat", "repeat_id", "fold", "fold_id", "gene_id", "original_column_index"}))
        previous_overlap = normalize_keys(read(source / "top50_feature_overlap.csv"))
        previous_frequency = read(source / "top50_feature_selection_frequency.csv")
        catalog = read(catalog_path)
        performance_folds = normalize_keys(read(source / "top50_comparison_fold_results.csv"))
        previous_performance_summary = read(source / "top50_comparison_summary.csv")
        check("原始基因列名记录完整且唯一", len(catalog) == catalog.gene_id.nunique() == 20531 and catalog.gene_id.notna().all())
        gene_ids = catalog.gene_id.tolist()
        gene_positions = {gene: i for i, gene in enumerate(gene_ids)}
        check("方法标识恰好ANOVA及高方差两种", set(selected.method) == set(METHODS))
        check("10000条选中特征记录完整", len(selected) == 10000 and selected.gene_id.notna().all())
        check("基因名称与原始矩阵列名记录一致", selected.gene_id.isin(gene_ids).all())
        if "original_column_index" in selected:
            positions = pd.to_numeric(selected.original_column_index, errors="raise").to_numpy()
            check("原始基因列号为有效整数", np.equal(positions, np.floor(positions)).all() and ((positions >= 0) & (positions < 20531)).all())
            check("每个基因名与原始列位置逐行对应", np.array_equal(np.asarray(gene_ids)[positions.astype(int)], selected.gene_id))
        expected_keys = {(repeat, fold) for repeat in range(1, 21) for fold in range(1, 6)}
        sets, set_keys = {}, {}
        for method in METHODS:
            grouped = selected.loc[selected.method.eq(method)].groupby(KEYS, sort=True)
            check(f"{method}恰好100个训练折记录", grouped.ngroups == 100)
            check(f"{method}完整20×5编号无缺失", set(grouped.groups) == expected_keys)
            method_keys = []
            for (repeat, fold), group in grouped:
                check(f"{method}/轮{repeat}/折{fold}恰好50个不重复基因", len(group) == group.gene_id.nunique() == 50)
                check(f"{method}/轮{repeat}/折{fold}仅一个evaluation_id", group.evaluation_id.nunique() == 1)
                key = (int(repeat), int(fold))
                sets[(method, *key)] = frozenset(group.gene_id)
                method_keys.append(key)
            set_keys[method] = method_keys
        check("两方法repeat/fold能一一配对", set_keys[METHODS[0]] == set_keys[METHODS[1]])
        print("检查通过：每方法100个集合，每集合50个唯一基因，20×5编号完整且一致。", flush=True)

        pair_rows, summary_rows = [], []
        frequency_rows, frequency_summary_rows = [], []
        for method in METHODS:
            method_rows = []
            # 不去重内容相同的集合：比较的是100条不同训练折记录的4950个无序对。
            for first, second in combinations(set_keys[method], 2):
                a, b = sets[(method, *first)], sets[(method, *second)]
                common, union = len(a & b), len(a | b)
                row = {"method": method, "repeat_id_i": first[0], "fold_id_i": first[1],
                       "evaluation_id_i": (first[0] - 1) * 5 + first[1],
                       "repeat_id_j": second[0], "fold_id_j": second[1],
                       "evaluation_id_j": (second[0] - 1) * 5 + second[1],
                       "overlap_count": common, "union_count": union, "jaccard": common / union,
                       "same_repeat": first[0] == second[0], "identical_gene_content": a == b}
                method_rows.append(row)
            pair_rows.extend(method_rows)
            part = pd.DataFrame(method_rows)
            check(f"{method}4950个不同训练折无序对", len(part) == 4950 and not part.duplicated(["evaluation_id_i", "evaluation_id_j"]).any())
            # 以100×基因的二值矩阵独立复核集合交集；只使用已选基因，不评分表达值。
            union_genes = sorted(set.union(*(set(sets[(method, *key)]) for key in set_keys[method])), key=gene_positions.get)
            indicator = np.asarray([[int(g in sets[(method, *key)]) for g in union_genes] for key in set_keys[method]], dtype=np.int32)
            intersections = indicator @ indicator.T
            ii, jj = np.triu_indices(100, k=1)
            check(f"{method}集合循环与二值矩阵独立复算交集一致", np.array_equal(part.overlap_count, intersections[ii, jj]))
            check(f"{method}Jaccard独立公式复算一致", np.allclose(part.jaccard, intersections[ii, jj] / (100 - intersections[ii, jj]), atol=1e-14))
            summary_rows.append({"comparison": "within_method", "method": method, "method_label": NAMES[method],
                                 "n_feature_set_records": 100, **describe(part.jaccard),
                                 "mean_overlap_count": float(part.overlap_count.mean()),
                                 "overlap_count_min": int(part.overlap_count.min()), "overlap_count_max": int(part.overlap_count.max()),
                                 "n_unique_gene_contents": len({sets[(method, *key)] for key in set_keys[method]})})
            counts = selected.loc[selected.method.eq(method)].gene_id.value_counts().reindex(gene_ids, fill_value=0)
            frequency_table = pd.DataFrame({"method": method, "gene_id": gene_ids, "original_column_index": np.arange(20531),
                                            "selected_fold_count": counts.to_numpy(), "n_training_folds": 100,
                                            "selection_frequency": counts.to_numpy() / 100,
                                            "selection_percentage": counts.to_numpy(),
                                            "selected_all_100_folds": counts.to_numpy() == 100})
            rank_order = np.argsort(-counts.to_numpy(), kind="stable")
            ranks = np.empty(20531, dtype=int)
            ranks[rank_order] = np.arange(1, 20532)
            frequency_table["frequency_display_rank"] = ranks
            frequency_table["displayed_top20"] = ranks <= 20
            frequency_rows.extend(frequency_table.to_dict("records"))
            frequency_summary_rows.append({"method": method, "n_training_folds": 100,
                                            "n_genes_ever_selected": int(counts.gt(0).sum()), "n_genes_selected_all_100": int(counts.eq(100).sum()),
                                            "n_unique_gene_contents": len({sets[(method, *key)] for key in set_keys[method]}),
                                            "total_gene_selections": int(counts.sum())})
            saved = previous_frequency.loc[previous_frequency.method.eq(method)].set_index("gene_id")
            check(f"{method}原频率表覆盖全部20531基因且无重复", len(saved) == len(set(saved.index)) == 20531 and set(saved.index) == set(gene_ids))
            saved = saved.loc[gene_ids]
            check(f"{method}重新计数与原频数一致", np.array_equal(counts, saved.selected_fold_count))
            check(f"{method}重新计数与原频率一致", np.allclose(counts / 100, saved.selection_frequency, atol=1e-14))
            check(f"{method}总入选数为100×50", counts.sum() == 5000)
        within = pd.DataFrame(pair_rows)
        save(within, "jaccard_within_method_pairs")

        between_rows = []
        for repeat, fold in set_keys[METHODS[0]]:
            a, b = [sets[(method, repeat, fold)] for method in METHODS]
            common, union = a & b, a | b
            between_rows.append({"repeat_id": repeat, "fold_id": fold, "evaluation_id": (repeat - 1) * 5 + fold,
                                  "method_A": METHODS[0], "method_B": METHODS[1], "overlap_count": len(common),
                                  "union_count": len(union), "jaccard": len(common) / len(union),
                                  "overlap_gene_ids": ";".join(sorted(common, key=gene_positions.get))})
        between = pd.DataFrame(between_rows)
        check("同折比较恰好100次且无重复", len(between) == 100 and not between.duplicated(KEYS).any())
        check("原同折重合表100条且编号唯一", len(previous_overlap) == 100 and not previous_overlap.duplicated(KEYS).any())
        joined = between.merge(previous_overlap[KEYS + ["overlap_count", "union_count", "jaccard"]], on=KEYS,
                                validate="one_to_one", suffixes=("", "_previous"))
        check("同折编号未错配到不同折", len(joined) == 100)
        for field in ("overlap_count", "union_count", "jaccard"):
            check(f"重新计算同折{field}与原记录一致", np.allclose(joined[field], joined[f"{field}_previous"], atol=1e-14))
        save(between, "jaccard_between_methods_by_fold")
        summary_rows.append({"comparison": "between_methods_same_fold", "method": "anova_vs_variance",
                             "method_label": "ANOVA与高方差（同轮同折）", "n_feature_set_records": 100,
                             **describe(between.jaccard), "mean_overlap_count": float(between.overlap_count.mean()),
                             "overlap_count_min": int(between.overlap_count.min()), "overlap_count_max": int(between.overlap_count.max()),
                             "n_unique_gene_contents": None})
        summary, frequencies, frequency_methods = pd.DataFrame(summary_rows), pd.DataFrame(frequency_rows), pd.DataFrame(frequency_summary_rows)
        save(summary, "jaccard_stability_summary")
        save(frequencies, "feature_selection_frequency_summary")
        save(frequency_methods, "feature_frequency_method_summary")
        performance_rows = []
        for method in METHODS:
            part = performance_folds.loc[performance_folds.method.eq(method)]
            check(f"{method}历史性能恰好100折且一一对应", len(part) == 100 and not part.duplicated(KEYS).any() and set(map(tuple, part[KEYS].to_numpy())) == expected_keys)
            previous = previous_performance_summary.loc[previous_performance_summary.method.eq(method)]
            check(f"{method}历史性能摘要唯一", len(previous) == 1)
            f1, ba = part.validation_macro_f1.mean(), part.validation_balanced_accuracy.mean()
            check(f"{method}Macro-F1与原摘要一致", np.isclose(f1, previous.validation_macro_f1_mean.iloc[0], rtol=0, atol=1e-12))
            check(f"{method}Balanced Accuracy与原摘要一致", np.isclose(ba, previous.validation_balanced_accuracy_mean.iloc[0], rtol=0, atol=1e-12))
            js = summary.loc[summary.method.eq(method)].iloc[0]
            performance_rows.append({"method": method, "historical_validation_macro_f1_mean": float(f1),
                                     "historical_validation_macro_f1_sample_std": float(part.validation_macro_f1.std(ddof=1)),
                                     "historical_balanced_accuracy_mean": float(ba), "within_method_jaccard_mean": js["mean"],
                                     "within_method_jaccard_sample_std": js.sample_std})
        performance = pd.DataFrame(performance_rows)
        save(performance, "performance_stability_comparison")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            font = plot_results(output, within, between, frequencies, frequency_methods)
        check("图中无缺字警告", not any("Glyph" in str(w.message) and "missing" in str(w.message) for w in caught))
        for name in ("jaccard_stability_comparison", "jaccard_between_methods", "feature_selection_frequency_top20"):
            with Image.open(output / f"{name}.png") as img:
                img.verify()
            with Image.open(output / f"{name}.png") as img:
                check(f"{name} PNG完整且≥300DPI", min(img.info.get("dpi", (0, 0))) >= 300)
            check(f"{name} PDF版本存在", (output / f"{name}.pdf").read_bytes().startswith(b"%PDF"))
        for record in input_records:
            check(f"源文件未修改：{Path(record['path']).name}", hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() == record["sha256"])
        report(output, summary, between, frequency_methods, performance)
        audit = {"passed": True, "n_checks": len(checks), "checks": checks,
                 "source_experiment_directory": str(source), "input_files": input_records,
                 "raw_expression_or_labels_loaded": False, "reserved_test_sample_records_loaded": False,
                 "anova_recomputed": False, "gene_variances_recomputed": False, "classifier_fits": 0,
                 "independent_sample_significance_tests_performed": False, "std_ddof": 1,
                 "within_pairs_per_method": 4950, "between_method_pairs": 100,
                 "identical_gene_contents_not_deduplicated": True,
                 "field_mapping": {"repeat_id": "round", "fold_id": "fold"},
                 "font": font, "random_sampling_performed": False,
                 "frequency_tie_break": "original_gene_column_order; not F-score/variance/importance ranking",
                 "environment": {"python": sys.version, "platform": platform.platform(),
                                 "numpy": np.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__}}
        json_write(output / "analysis_audit.json", audit)
        (output / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
        json_write(results_dir / "latest_jaccard_analysis.json", {"run_directory": str(output.relative_to(results_dir)), "status": "complete"})
        print(summary[["method_label", "n_comparisons", "mean", "sample_std", "min", "max", "median"]].to_string(index=False), flush=True)
        print(f"检查{len(checks)}项通过；无表达值读取、无评分重算、无模型拟合。结果：{output}", flush=True)
        return output
    except Exception as exc:
        json_write(output / "analysis_failure.json", {"status": "failed", "error": str(exc), "checks_passed_before_failure": checks})
        raise


def report(output, summary, between, frequency_methods, performance):
    stats = summary.set_index("method")
    perf, freq = performance.set_index("method"), frequency_methods.set_index("method")
    anova, variance = stats.loc[METHODS[0]], stats.loc[METHODS[1]]
    f_delta = perf.loc[METHODS[0], "historical_validation_macro_f1_mean"] - perf.loc[METHODS[1], "historical_validation_macro_f1_mean"]
    j_delta = variance["mean"] - anova["mean"]
    paragraph = (f"在固定640例开发样本的20轮重复5折交叉验证中，高方差Top50的平均两两Jaccard为{variance['mean']:.5f}，高于ANOVA Top50的{anova['mean']:.5f}，"
                 f"表明前者在本次训练样本扰动下具有更高的基因集合一致性。两方法同折平均Jaccard仅为{between.jaccard.mean():.5f}，平均重合{between.overlap_count.mean():.2f}/50个基因，"
                 f"显示两种筛选准则产生的基因集合存在较大差异。尽管ANOVA的Macro-F1略高（{perf.loc[METHODS[0], 'historical_validation_macro_f1_mean']:.8f}对"
                 f"{perf.loc[METHODS[1], 'historical_validation_macro_f1_mean']:.8f}），其特征选择稳定性反而较低，因此较高的内部分类性能并不必然对应更稳定的基因选择。"
                 "以上仅为相关重复划分下的描述性结果，不构成统计显著性或外部泛化能力的证明。")
    lines = ["# 既有Top50记录的Jaccard稳定性与方法间重合分析", "",
             "## 数据来源与检查", "",
             "只读取既有选中特征、同折重合、入选频率及分类成绩CSV；基因名校验依据最初数据读取阶段导出的gene_columns.csv。本次没有打开原始表达矩阵或标签文件，也未读取161个保留样本的记录。",
             "原记录round→repeat_id、fold→fold_id，evaluation_id=(repeat_id−1)×5+fold_id。每方法恰好100个训练折记录，每记录50个不重复基因，编号覆盖20×5并严格一一配对。",
             "方法内遍历不同训练折记录i<j的4950个无序对；即使两个训练折选出的基因完全相同，仍保留该比较并记J=1。不能对集合内容去重后再改变样本量。",
             "同折比较仅100次，按相同repeat_id和fold_id配对，不使用两方法不同折的笛卡尔积。集合循环结果另用二值入选矩阵的乘积独立复核，原频率表与原同折重合表也逐项核对。", "",
             "## 三类Jaccard统计", "", "J(A,B)=|A∩B|/|A∪B|；每个集合50个基因，所以J=重合数/(100−重合数)。标准差ddof=1。", "",
             "|比较|比较次数|均值|样本标准差|最小值|最大值|中位数|", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary.itertuples():
        lines.append(f"|{row.method_label}|{row.n_comparisons}|{row.mean:.8f}|{row.sample_std:.8f}|{row.min:.8f}|{row.max:.8f}|{row.median:.8f}|")
    lines += ["", "## 六个问题的回答", "",
              f"1. ANOVA Top50平均两两Jaccard为 **{anova['mean']:.8f}**。",
              f"2. 高方差Top50平均两两Jaccard为 **{variance['mean']:.8f}**。",
              f"3. 本次高方差方法的基因集合更加稳定；均值高出 **{j_delta:.8f}**。这不是说其分类性能更高或基因更有生物学价值。",
              f"4. 两种方法同折平均Jaccard为 **{between.jaccard.mean():.8f}**，样本SD={between.jaccard.std(ddof=1):.8f}；每折平均重合 **{between.overlap_count.mean():.2f}** 个，范围{between.overlap_count.min()}–{between.overlap_count.max()}个。每折结果见jaccard_between_methods_by_fold.csv。",
              f"5. 两者有共同选择的部分，但整体并不是相同的Top50；平均共同基因占每组50个的 **{between.overlap_count.mean()/50:.2%}**。低方法间Jaccard不等于完全没有共同基因，也不说明不存在相关表达信号。",
              f"6. 是：分类性能很接近，但特征选择稳定性描述性差异清楚。ANOVA Macro-F1={perf.loc[METHODS[0], 'historical_validation_macro_f1_mean']:.8f}，高方差={perf.loc[METHODS[1], 'historical_validation_macro_f1_mean']:.8f}；ANOVA仅高 **{f_delta*100:.5f}个百分点**，其Jaccard却低 **{j_delta:.5f}**。性能均值方向与特征稳定性方向相反。",
              "此处比较的是两种固定方法，不能据此估计一般性的性能—稳定性相关规律，更不能解释为因果关系。预测分数的折间标准差、整轮OOF波动与基因集合Jaccard也不是同一个指标。", "",
              "## 入选频率与Top20并列", "", "|方法|曾入选基因数|100折均入选基因数|不同集合内容数|", "|---|---:|---:|---:|"]
    for method in METHODS:
        row = freq.loc[method]
        lines.append(f"|{NAMES[method]}|{int(row.n_genes_ever_selected)}|{int(row.n_genes_selected_all_100)}|{int(row.n_unique_gene_contents)}|")
    lines += ["", "本次两方法均超过20个基因在100折中始终入选，所以Top20频率全部为100%。图中同频按原始基因列序选择展示；展示顺序不代表F-score、方差或生物学重要性。其余同为100%的基因仍完整保存在频率CSV中，不能因未画入Top20就认为不稳定。",
              "## 统计与研究边界", "",
              "4950个比较值反复共享100个特征集合，各训练折的样本还高度重叠；100个同折Jaccard也共享同一开发队列。因此不把它们视为4950或100个独立统计样本，不作普通独立样本t检验、显著性推断或独立样本置信区间。",
              "本次结果只描述既有重复CV中的选择一致性，不能代替RQ2中预定的30次分层子采样稳定性实验。没有新训练、没有新的ANOVA或方差计算、没有Top-K消融或测试集评估。",
              "没有证明两方法等效、ANOVA显著优于另一方法或高方差特征具有更可靠的生物学因果意义；也未证明外部队列泛化。", "",
              "## 可用于课程论文的简洁结论", "", paragraph, "",
              "## 输出与复现", "",
              "四份必需CSV、三张330DPI PNG及PDF均在本目录；另有Top20名单、频率方法摘要、性能—稳定性并列表和analysis_audit.json。",
              "```powershell", "python analyze_top50_stability.py", "```", "",
              "也可用--source-run指定已完成对照实验目录，--gene-catalog指定原始列名记录；缺失记录会明确报错，不填造数据。"]
    (output / "稳定性与基因重合分析报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "课程论文简洁结论.md").write_text(paragraph + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path)
    parser.add_argument("--gene-catalog", type=Path)
    args = parser.parse_args()
    cfg = ExperimentConfig()
    source_dir = args.source_run.resolve() if args.source_run else cfg.output_dir / json_read(cfg.output_dir / "latest_top50_comparison.json")["run_directory"]
    catalog = args.gene_catalog.resolve() if args.gene_catalog else cfg.output_dir / json_read(cfg.output_dir / "latest_stage1.json")["run_directory"] / "gene_columns.csv"
    try:
        analyze(source_dir, catalog, cfg.output_dir)
    except Exception as error:
        print(f"既有结果稳定性分析失败：{error}", file=sys.stderr)
        raise SystemExit(1)
