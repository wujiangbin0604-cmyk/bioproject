# -*- coding: utf-8 -*-
"""第三阶段可复用组件：共享分层子采样、ANOVA/线性SVM排名和 Jaccard。"""
from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_selection import f_classif
from sklearn.model_selection import StratifiedShuffleSplit

from baseline import build_baseline
from config import ExperimentConfig
from data_loader import DevelopmentData


def make_subsample_indices(development: DevelopmentData, cfg: ExperimentConfig) -> list[np.ndarray]:
    """只从开发集取30次分层80%子样本；两个选择器和所有K必须共用此列表。"""
    splitter = StratifiedShuffleSplit(n_splits=cfg.stability_subsamples,
                                      train_size=cfg.stability_fraction, random_state=cfg.random_state)
    return [train.copy() for train, _ in splitter.split(development.X, development.y)]


def rank_subsample_features(X_sub: pd.DataFrame, y_sub: pd.Series,
                            method: str, cfg: ExperimentConfig) -> pd.Series:
    """每个子样本/方法只拟合一次排名，可供全部K使用；当前阶段不调用。

    多分类线性 SVM 对每个基因的各类别系数取 L2 范数，再做 Top-K；系数来自仅在
    当前子样本上拟合的标准化表达特征，不能在全开发集拟合后再抽取子样本。
    """
    if not X_sub.index.equals(y_sub.index):
        raise ValueError("子采样的 X 与 y 必须按样本 ID 对齐")
    if method == "anova":
        with warnings.catch_warnings(record=True):
            scores, _ = f_classif(X_sub, y_sub)
        # 常数特征的 NaN 不能排在有效评分之前；仅当前子样本局部处理。
        scores = np.nan_to_num(scores, nan=-np.inf, posinf=np.inf, neginf=-np.inf)
    elif method == "linear_svc_coefficients":
        model = build_baseline(cfg)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            model.fit(X_sub, y_sub)
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            raise RuntimeError("子样本 LinearSVC 未收敛，不能用不稳定的数值解解释特征稳定性")
        scores = np.linalg.norm(model.named_steps["model"].coef_, ord=2, axis=0)
    else:
        raise ValueError("method 应为 anova 或 linear_svc_coefficients")
    return pd.Series(scores, index=X_sub.columns, name="score").sort_values(ascending=False, kind="stable")


def mean_pairwise_jaccard(feature_sets: list[set[str]]) -> float:
    """30个选择集合有435对；其均值是描述统计，不视为435个独立观察。"""
    if len(feature_sets) < 2 or any(not selected for selected in feature_sets):
        raise ValueError("至少需要两个非空特征集合")
    return float(np.mean([len(a & b) / len(a | b) for a, b in itertools.combinations(feature_sets, 2)]))


def selection_frequencies(feature_sets: list[set[str]], gene_names: pd.Index) -> pd.DataFrame:
    """保留包括从未入选的基因，分母为真实子采样次数。"""
    if not feature_sets:
        raise ValueError("尚无真实子采样结果，不能生成入选频率")
    unknown = set().union(*feature_sets) - set(gene_names)
    if unknown:
        raise ValueError("选择集合中包含原始数据不存在的基因")
    counts = [sum(name in selected for selected in feature_sets) for name in gene_names]
    return pd.DataFrame({"gene_id": gene_names, "selection_count": counts,
                         "selection_frequency": np.asarray(counts) / len(feature_sets)})


if __name__ == "__main__":
    print("第三阶段组件已预留。当前未执行30次子采样，不生成稳定性数值。")
