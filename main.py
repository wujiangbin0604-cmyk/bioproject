# -*- coding: utf-8 -*-
"""实验入口：当前仅启用第一阶段；后续阶段不会自动执行。"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import platform
from pathlib import Path
import sys
import time
import traceback

import matplotlib
import numpy as np
import pandas as pd
import scipy
import sklearn
from threadpoolctl import threadpool_info

from baseline import build_baseline
from config import ExperimentConfig
from cross_validation import evaluate_fixed_pipeline, make_cv
from data_loader import prepare_development_data, write_json
from evaluation import save_development_oof_report
from visualization import plot_baseline_cv, plot_development_confusion


def environment_record() -> dict:
    return {"python": sys.version, "python_executable": sys.executable,
            "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__, "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__, "threadpools": threadpool_info()}


def run_stage1(cfg: ExperimentConfig) -> Path:
    """执行固定基线五折；不调参、不训练最终模型、不预测保留测试集。"""
    if cfg.cv_mode != "standard":
        raise ValueError("第一阶段固定使用 standard。repeated 模式留待第六阶段评估冻结配置；可用 --describe-cv 查看")
    np.random.seed(cfg.random_state)
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
    output = cfg.output_dir / "stage1_baseline" / stamp
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "config.json", cfg.to_dict())
    write_json(output / "environment.json", environment_record())
    plan = {
        "stage_1": "running", "stage_2": "not_run", "stage_3": "not_run",
        "stage_4": "not_run", "stage_5": "not_run", "stage_6": "not_run",
        "test_evaluation_performed": False, "hyperparameter_search_performed": False,
        "baseline_C_fixed_a_priori": cfg.baseline_c,
    }
    write_json(output / "stage_status.json", plan)
    start = time.perf_counter()
    try:
        print("读取原始数据、检查样本ID与数据质量...", flush=True)
        development = prepare_development_data(cfg, output)
        print(f"开发集 {development.X.shape}；保留测试样本 {len(development.reserved_test_ids)}。", flush=True)
        print(f"全特征基线固定 C={cfg.baseline_c}；仅执行开发集分层5折CV。", flush=True)
        results = evaluate_fixed_pipeline(build_baseline(cfg), development, cfg, output)
        save_development_oof_report(results["predictions"], output)
        plot_baseline_cv(results["details"], output / "figures")
        confusion = pd.read_csv(output / "development_oof_confusion_matrix.csv", index_col=0)
        plot_development_confusion(confusion, output / "figures")
        summary = results["summary"].iloc[0]
        report = [
            "# 第一阶段：全特征 Linear SVM 基线", "",
            f"真实数据：801 个样本、20,531 个基因；开发集 {len(development.X)} 个样本，保留测试集 {len(development.reserved_test_ids)} 个样本。",
            "所有原始基因均保留，无全数据标准化、填补、筛选或 PCA。", "",
            "固定流程为 StandardScaler → LinearSVC(C=1.0, dual='auto')，仅在开发集执行 StratifiedKFold(5, shuffle=True, random_state=42)。每折重新克隆 Pipeline，并仅用当前训练折拟合。", "",
            f"验证 Macro-F1：{summary.validation_macro_f1_mean:.6f} ± {summary.validation_macro_f1_std:.6f}。",
            f"验证 Balanced Accuracy：{summary.validation_balanced_accuracy_mean:.6f} ± {summary.validation_balanced_accuracy_std:.6f}。",
            f"训练减验证 Macro-F1 平均差距：{summary.gap_macro_f1_mean:.6f}。",
            f"训练减验证 Balanced Accuracy 平均差距：{summary.gap_balanced_accuracy_mean:.6f}。", "",
            "以上均值和样本标准差(ddof=1)来自5个验证折，只是开发CV的描述统计，不是独立测试结果，也不作为5次独立实验的置信区间。",
            "development_oof_* 文件仅汇总640个开发样本各一次折外预测；合并OOF指标与折分数简单平均可能略有不同。", "",
            "保留测试集没有进入模型拟合、特征选择、预测、评分或参数比较。最终独立测试分类报告与混淆矩阵尚未生成。",
            "阶段2至6均未执行；本阶段没有选出最终K或最终C，也没有训练最终全开发集模型。", "",
            "fold_fit_audit.csv 核验每折标准化器样本数、均值和方差，以及训练/验证/保留测试的ID交集。所有输出由本次真实运行产生。", "",
            "## 研究边界", "",
            "此前探索性可视化已使用全数据。因此，这个保留测试集只是在当前机器学习开发流程中隔离，并非从未查看过的外部数据；请在论文中披露，避免声称完全独立的外部验证。",
            "数据只覆盖五类已患癌样本，不能把高分类分数解释为癌症早筛或健康/患癌诊断性能。",
        ]
        (output / "阶段一结果说明.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        plan.update(stage_1="complete", elapsed_seconds=time.perf_counter() - start,
                    n_development=len(development.X), n_reserved_test=len(development.reserved_test_ids),
                    n_cv_evaluations=len(results["details"]), all_fold_audits_passed=True)
        write_json(output / "stage_status.json", plan)
        write_json(cfg.output_dir / "latest_stage1.json",
                   {"run_directory": str(output.relative_to(cfg.output_dir)), "status": "complete"})
        print(results["summary"].to_string(index=False), flush=True)
        print(f"第一阶段完成；结果目录：{output}", flush=True)
        return output
    except Exception as exc:
        plan.update(stage_1="failed", error=str(exc), elapsed_seconds=time.perf_counter() - start)
        write_json(output / "stage_status.json", plan)
        (output / "error_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="癌症基因表达分类实验；目前仅执行第一阶段")
    parser.add_argument("--stage", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--cv-mode", choices=("standard", "repeated"), default=None)
    parser.add_argument("--describe-cv", action="store_true", help="只描述CV结构，不读取数据、不拟合")
    parser.add_argument("--data-dir", type=Path, help="同时包含 data.csv、labels.csv 的目录")
    parser.add_argument("--archive", type=Path, help="含两份CSV的真实TAR/TAR.GZ")
    parser.add_argument("--permute-labels", action="store_true", help="独立启动开发集标签置乱负对照；仅用于repeated")
    parser.add_argument("--permutation-seed", type=int, default=42, help="仅标签置乱的随机种子，默认42")
    args = parser.parse_args(argv)
    cfg = ExperimentConfig()
    if args.cv_mode:
        cfg = replace(cfg, cv_mode=args.cv_mode)
    if args.data_dir:
        cfg = replace(cfg, data_dir=args.data_dir.resolve())
    if args.archive:
        cfg = replace(cfg, raw_archive=args.archive.resolve())
    if args.describe_cv:
        print(f"模式 {cfg.cv_mode}：{make_cv(cfg).get_n_splits()} 次验证评估；本命令未读取数据或拟合模型。")
        if cfg.cv_mode == "repeated":
            print("结构为5折×20次，不是100折；100个分数有关联，只对冻结配置描述波动。")
        return 0
    if args.stage != 1:
        parser.error(f"阶段 {args.stage} 仅预留框架，当前未启用，防止一次性执行后续实验")
    if args.permute_labels and cfg.cv_mode != "repeated":
        parser.error("--permute-labels 只适用于 --cv-mode repeated，避免改变原五折真实标签基线")
    try:
        if cfg.cv_mode == "repeated":
            from repeated_cv import run_repeated_experiment
            run_repeated_experiment(cfg, args.permute_labels, args.permutation_seed)
        else:
            run_stage1(cfg)
        return 0
    except Exception as exc:
        print(f"第一阶段失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
