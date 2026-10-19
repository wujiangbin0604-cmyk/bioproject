# -*- coding: utf-8 -*-
"""Pipeline兼容的原表达方差TopK；仅在fit接收到的训练折上计算。"""
from numbers import Integral

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.feature_selection import SelectorMixin
from sklearn.utils.validation import check_array, check_is_fitted


class VarianceTopK(SelectorMixin, BaseEstimator):
    """按样本方差(ddof=1)选K列；同方差按原列位置从小到大。

    transform保留原列顺序，便于核对训练和验证输入；选择排名另存属性。
    不标准化、不使用y，也不读取任何探索性Top50文件。
    """

    def __init__(self, k=50):
        self.k = k

    def fit(self, X, y=None):
        array = check_array(X, dtype=np.float64, accept_sparse=False)
        if not isinstance(self.k, Integral) or isinstance(self.k, bool) or not 1 <= self.k <= array.shape[1]:
            raise ValueError("k必须是1到特征总数之间的整数")
        if len(array) < 2:
            raise ValueError("样本方差至少需要两个训练样本")
        self.n_features_in_ = array.shape[1]
        if hasattr(X, "columns") and all(isinstance(c, str) for c in X.columns):
            self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.n_samples_seen_ = len(array)
        self.variances_ = array.var(axis=0, ddof=1)
        if not np.isfinite(self.variances_).all():
            raise ValueError("训练折方差出现非有限值")
        # 稳定排序使方差并列时保留原始列顺序，保证特征选择可复现。
        self.selected_indices_by_rank_ = np.argsort(-self.variances_, kind="stable")[:self.k]
        self.support_mask_ = np.zeros(self.n_features_in_, dtype=bool)
        self.support_mask_[self.selected_indices_by_rank_] = True
        return self

    def _get_support_mask(self):
        check_is_fitted(self, ("variances_", "support_mask_"))
        return self.support_mask_
