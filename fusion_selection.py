# -*- coding: utf-8 -*-
"""折内融合选择器、确定性集合规则及可审计的 Pipeline 拟合。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import time
import warnings
from unittest.mock import patch

import numpy as np
from sklearn.base import BaseEstimator, clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_selection import SelectorMixin, f_classif
from sklearn.utils.validation import check_array, check_is_fitted
from threadpoolctl import threadpool_limits

from ablation_engine import (METRICS, atomic_json, load_checkpoint, rank_scores,
                             raw_training_statistics, save_checkpoint, scores, validate_anova)
from baseline import build_baseline


@dataclass(frozen=True)
class Scheme:
    name: str
    rule: str
    k: int
    increment: int = 0
    experiment: str = "A"
    fixed_budget: bool = True


def schemes():
    result = []
    for k in (20, 50):
        for rule in ("anova", "variance", "fusion_equal", "fusion_anova75", "fusion_variance75"):
            result.append(Scheme(f"{rule}_k{k}", rule, k))
        for rule in ("intersection", "union", "anova_only", "variance_only", "anova_matched_union", "variance_matched_union"):
            result.append(Scheme(f"{rule}_k{k}", rule, k, experiment="B", fixed_budget=False))
    for increment in (10, 20, 30):
        result.append(Scheme(f"add_variance_{increment}", "add_variance", 50, increment, "C"))
        for rule in ("anova", "variance"):
            k = 50 + increment
            result.append(Scheme(f"{rule}_k{k}", rule, k, experiment="C"))
    assert len(result) == len({s.name for s in result}) == 31
    return result


def choose_features(anova_rank, variance_rank, rule, k, increment=0):
    """只依赖训练子集的两种完整排名；返回原列位置升序，不使用验证结果。"""
    a, b = np.asarray(anova_rank, int), np.asarray(variance_rank, int)
    aset, bset = set(a[:k]), set(b[:k])
    if rule == "anova":
        selected = a[:k]
    elif rule == "variance":
        selected = b[:k]
    elif rule in ("fusion_equal", "fusion_anova75", "fusion_variance75", "add_variance"):
        if rule == "fusion_equal":
            quota, target, primary, secondary = (k + 1) // 2, k, a, b
        elif rule == "fusion_anova75":
            quota, target, primary, secondary = (3 * k + 2) // 4, k, a, b
        elif rule == "fusion_variance75":
            quota, target, primary, secondary = (3 * k + 2) // 4, k, b, a
        else:
            quota, target, primary, secondary = k, k + increment, a, b
        initial = primary[:quota].tolist()
        keep = set(initial)
        supplement = [int(g) for g in secondary if g not in keep][:target - quota]
        selected = initial + supplement
        if len(selected) != len(set(selected)) or len(selected) != target:
            raise ValueError("融合没有得到所需数量的不重复特征")
    elif rule == "intersection":
        selected = list(aset & bset)
    elif rule == "union":
        selected = list(aset | bset)
    elif rule == "anova_only":
        selected = list(aset - bset)
    elif rule == "variance_only":
        selected = list(bset - aset)
    elif rule == "anova_matched_union":
        selected = a[:len(aset | bset)]
    elif rule == "variance_matched_union":
        selected = b[:len(aset | bset)]
    else:
        raise ValueError(f"未知选择规则：{rule}")
    return np.sort(np.asarray(selected, dtype=int))


def training_digest(X, y):
    """缓存绑定到实际训练数值及标签顺序；不能用全开发集或其他折缓存冒充。"""
    h = hashlib.sha256()
    h.update(memoryview(np.ascontiguousarray(X, dtype=np.float64)).cast("B"))
    h.update(json.dumps(np.asarray(y, str).tolist(), ensure_ascii=False).encode())
    return h.hexdigest()


def prepare_scores(X, y, path, identity, scope_ids):
    digest = training_digest(X, y)
    current = load_checkpoint(path, identity)
    if current is not None:
        if current[0]["training_digest"] != digest or current[0]["sample_ids"] != list(scope_ids):
            raise ValueError("排名缓存不属于当前训练样本")
        return current
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
        warnings.simplefilter("always")
        variance, manual_f, constant = raw_training_statistics(X, y)
        actual_f, _ = f_classif(X, y)
        validate_anova(actual_f, manual_f, constant)
    metadata = {"identity": identity, "training_digest": digest, "sample_ids": list(scope_ids),
                "n_samples": len(X), "n_features": X.shape[1], "n_constant": int(constant.sum()),
                "anova_nan_count": int(np.isnan(actual_f).sum()), "anova_inf_count": int(np.isinf(actual_f).sum()),
                "independent_score_audit_passed": True,
                "warnings": [{"category": w.category.__name__, "message": str(w.message)} for w in caught]}
    save_checkpoint(path, metadata, variance=variance, anova=actual_f, constant=constant,
                    anova_rank=rank_scores(actual_f, "anova"), variance_rank=rank_scores(variance, "variance"))
    return load_checkpoint(path, identity)


class FusionSelector(SelectorMixin, BaseEstimator):
    """sklearn clone/Pipeline 兼容；可复用严格同训练折的评分，不读全局名单。"""
    def __init__(self, rule="fusion_equal", k=50, increment=0, cache_path=None, cache_identity=None):
        self.rule, self.k, self.increment = rule, k, increment
        self.cache_path, self.cache_identity = cache_path, cache_identity

    def fit(self, X, y):
        a = check_array(X, dtype=np.float64)
        self.n_features_in_, self.n_samples_seen_ = a.shape[1], len(a)
        if self.cache_path is None:
            variance, manual_f, constant = raw_training_statistics(a, np.asarray(y))
            f, _ = f_classif(a, y)
            validate_anova(f, manual_f, constant)
            self.anova_rank_, self.variance_rank_ = rank_scores(f, "anova"), rank_scores(variance, "variance")
            self.score_scope_audited_ = True
        else:
            record, arrays = load_checkpoint(self.cache_path, self.cache_identity)
            if record["training_digest"] != training_digest(a, y) or record["n_samples"] != len(a):
                raise ValueError("选择器收到的实际训练矩阵与评分缓存不一致")
            self.anova_rank_, self.variance_rank_ = arrays["anova_rank"], arrays["variance_rank"]
            constant = arrays["constant"]
            self.score_scope_audited_ = record["independent_score_audit_passed"]
        self.selected_indices_ = choose_features(self.anova_rank_, self.variance_rank_, self.rule, self.k, self.increment)
        if constant[self.selected_indices_].any():
            raise ValueError("选中集合包含常数基因，停止诊断")
        self.support_mask_ = np.zeros(self.n_features_in_, dtype=bool)
        self.support_mask_[self.selected_indices_] = True
        return self

    def _get_support_mask(self):
        check_is_fitted(self, "support_mask_")
        return self.support_mask_


def make_pipeline(cfg, scheme, score_path, identity):
    from sklearn.pipeline import Pipeline
    return Pipeline([("select", FusionSelector(scheme.rule, scheme.k, scheme.increment, str(score_path), identity)),
                     *clone(build_baseline(cfg)).steps])


def fit_task(X, y, train, valid, scheme, e, cfg, score_path, path, identity):
    existing = load_checkpoint(path, identity)
    if existing is not None:
        return existing[0]["metrics"]
    info, cached = load_checkpoint(score_path, identity)
    expected = choose_features(cached["anova_rank"], cached["variance_rank"], scheme.rule, scheme.k, scheme.increment)
    n = len(expected)
    row = {**asdict(scheme), "scheme": scheme.name, "evaluation_id": e, "repeat_id": (e - 1) // 5 + 1,
           "fold_id": (e - 1) % 5 + 1, "n_train": 512, "n_validation": 128, "n_features": n,
           "C": 1.0, "result_origin": "new_fit", "status": "evaluated", "convergence_warning_count": 0}
    audit = {"scheme": scheme.name, "evaluation_id": e, "train_validation_overlap": 0, "reserved_test_overlap": 0,
             "score_cache_training_samples": 512, "score_scope_digest": info["training_digest"],
             "selector_fit_samples": 512, "selected_features": n, "scores_independently_audited": True}
    if n == 0:
        row.update(status="skipped_empty", result_origin="empty_no_model", fit_seconds=0.0, predict_seconds=0.0, max_solver_iterations=0)
        row.update({f"{prefix}_{m}": None for prefix in ("train", "validation", "gap") for m in METRICS})
        audit.update(selector_fit_calls=0, scaler_fit_calls=0, classifier_fit_calls=0, scaler_fit_audit_passed=None)
        save_checkpoint(path, {"identity": identity, "metrics": row, "audit": audit, "warnings": []},
                        selected=expected, train_pred=np.asarray([], str), valid_pred=np.asarray([], str))
        return row
    fitted = clone(make_pipeline(cfg, scheme, score_path, identity))
    selector, scaler, model = [fitted.named_steps[s] for s in ("select", "scale", "model")]
    assert not hasattr(selector, "support_mask_") and not hasattr(scaler, "mean_") and not hasattr(model, "coef_")
    raw, labels = X[train], y[train]
    with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg.numeric_threads):
        warnings.simplefilter("always")
        with patch.object(selector, "fit", wraps=selector.fit) as sf, patch.object(scaler, "fit", wraps=scaler.fit) as zf, patch.object(model, "fit", wraps=model.fit) as mf:
            start = time.perf_counter()
            fitted.fit(raw, labels)
            elapsed = time.perf_counter() - start
            assert sf.call_count == zf.call_count == mf.call_count == 1
            np.testing.assert_array_equal(sf.call_args.args[0], raw)
            np.testing.assert_array_equal(sf.call_args.args[1], labels)
            np.testing.assert_array_equal(selector.selected_indices_, expected)
            np.testing.assert_array_equal(zf.call_args.args[0], raw[:, expected])
            np.testing.assert_allclose(mf.call_args.args[0], scaler.transform(raw[:, expected]), rtol=1e-12, atol=1e-12)
            np.testing.assert_array_equal(mf.call_args.args[1], labels)
        start = time.perf_counter()
        tp, vp = fitted.predict(raw), fitted.predict(X[valid])
        prediction_seconds = time.perf_counter() - start
    captured = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        atomic_json(Path(path).with_suffix(".failure.json"), {"warnings": captured})
        raise RuntimeError(f"{scheme.name} 第{e}折未收敛，已停止且保留断点")
    np.testing.assert_allclose(scaler.mean_, raw[:, expected].mean(axis=0), rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(scaler.var_, raw[:, expected].var(axis=0), rtol=1e-10, atol=1e-12)
    assert np.all(np.asarray(scaler.n_samples_seen_) == 512) and model.n_features_in_ == n and np.isfinite(model.coef_).all()
    row.update(fit_seconds=elapsed, predict_seconds=prediction_seconds, max_solver_iterations=int(np.max(np.atleast_1d(model.n_iter_))))
    ts, vs = scores(labels, tp), scores(y[valid], vp)
    for m in METRICS:
        row.update({f"train_{m}": ts[m], f"validation_{m}": vs[m], f"gap_{m}": ts[m] - vs[m]})
    audit.update(selector_fit_calls=1, scaler_fit_calls=1, classifier_fit_calls=1, pipeline_unfitted_before_fit=True,
                 selector_actual_input_audited=True, selector_cache_digest_matches_actual_input=True,
                 scaler_training_samples=512, scaler_features=n, scaler_fit_audit_passed=True,
                 model_input_is_training_scaled=True, selected_indices_match_fold_rule=True,
                 n_constant_training_genes=info["n_constant"], n_undefined_anova_scores=info["anova_nan_count"])
    ar, vr = np.empty(X.shape[1], int), np.empty(X.shape[1], int)
    ar[cached["anova_rank"]] = np.arange(1, X.shape[1] + 1)
    vr[cached["variance_rank"]] = np.arange(1, X.shape[1] + 1)
    save_checkpoint(path, {"identity": identity, "metrics": row, "audit": audit, "warnings": captured},
                    selected=expected, train_pred=tp.astype(str), valid_pred=vp.astype(str),
                    anova_score=cached["anova"][expected], variance=cached["variance"][expected],
                    anova_rank=ar[expected], variance_rank=vr[expected])
    return row
