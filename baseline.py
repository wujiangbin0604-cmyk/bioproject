# -*- coding: utf-8 -*-
"""全特征 Linear SVM 基线：所有原始基因都进入折内标准化与分类。"""
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from config import ExperimentConfig


def build_baseline(cfg: ExperimentConfig) -> Pipeline:
    """返回未拟合的 Pipeline；C=1.0 为事先固定的基线，不在阶段一调参。"""
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", LinearSVC(C=cfg.baseline_c, penalty="l2", loss="squared_hinge",
                            dual="auto", class_weight=cfg.class_weight,
                            max_iter=cfg.max_iter, tol=cfg.tolerance,
                            random_state=cfg.random_state)),
    ])


if __name__ == "__main__":
    print(build_baseline(ExperimentConfig()))
    print("运行基线实验：python main.py --stage 1")
