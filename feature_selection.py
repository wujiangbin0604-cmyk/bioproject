# -*- coding: utf-8 -*-
"""第二阶段框架：折内 ANOVA → 标准化 → 线性 SVM / Logistic 回归。"""
from __future__ import annotations

from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from config import ExperimentConfig
from cross_validation import make_cv
from evaluation import SCORING


def build_anova_pipeline(cfg: ExperimentConfig, k: int, classifier: str = "linear_svm",
                         C: float = 1.0) -> Pipeline:
    """返回未拟合 Pipeline；不读取探索性项目的方差、差异或 PCA 结果。"""
    if k <= 0:
        raise ValueError("k 必须为正整数")
    if classifier == "linear_svm":
        model = LinearSVC(C=C, dual="auto", max_iter=cfg.max_iter, tol=cfg.tolerance,
                          class_weight=cfg.class_weight, random_state=cfg.random_state)
    elif classifier == "logistic_regression":
        model = LogisticRegression(C=C, solver="lbfgs", max_iter=cfg.max_iter,
                                   tol=cfg.tolerance, class_weight=cfg.class_weight,
                                   random_state=cfg.random_state)
    else:
        raise ValueError("classifier 只支持 linear_svm / logistic_regression")
    return Pipeline([("select", SelectKBest(score_func=f_classif, k=k)),
                     ("scale", StandardScaler()), ("model", model)])


def build_anova_search(cfg: ExperimentConfig, classifier: str = "linear_svm") -> GridSearchCV:
    """第二阶段调参接口；调用方只能对 development.X / development.y 执行 fit。

    best_score_ 是用于选模型的开发CV分数，不是无偏的最终泛化性能。
    不使用 repeated 的100个相关分数再次搜索后声称是固定配置鲁棒性评估。
    """
    if cfg.cv_mode != "standard":
        raise ValueError("超参数搜索使用 standard；repeated 保留给冻结配置的鲁棒性评估")
    return GridSearchCV(
        build_anova_pipeline(cfg, cfg.k_values[0], classifier),
        param_grid={"select__k": list(cfg.k_values), "model__C": list(cfg.c_grid)},
        scoring=SCORING, refit="macro_f1", cv=make_cv(cfg), n_jobs=cfg.n_jobs,
        return_train_score=True, error_score="raise",
    )


if __name__ == "__main__":
    search = build_anova_search(ExperimentConfig())
    print("第二阶段已预留，当前不拟合。参数网格：", search.param_grid)
