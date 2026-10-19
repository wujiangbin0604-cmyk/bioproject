# -*- coding: utf-8 -*-
"""RQ2：30 次共享分层子采样；系数法按多分类系数逐特征 L2 范数排序。"""
from __future__ import annotations

import itertools
import time
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_selection import f_classif
from sklearn.model_selection import StratifiedShuffleSplit
from threadpoolctl import threadpool_limits

from ablation_engine import (SELECTORS, atomic_json, build_pipeline, load_checkpoint, rank_scores,
                             raw_training_statistics, save_checkpoint, validate_anova)
from ablation_results import save
from config import CLASS_ORDER
from repeated_cv import descriptive


def run_stability(run, data, cfg, identity, log):
    """每次子采样只拟合一个全特征系数模型，再截取所有预定 K；没有验证评分。"""
    output = run / "stability"
    X, y = data.X.to_numpy(dtype=float), data.y.to_numpy(dtype=str)
    ids, genes = data.X.index.to_numpy(dtype=str), data.X.columns.to_numpy(dtype=str)
    splitter = StratifiedShuffleSplit(n_splits=cfg.stability_subsamples, train_size=cfg.stability_fraction, random_state=cfg.random_state)
    subsamples = list(splitter.split(X, y))
    indices = []
    audits, warning_rows = [], []
    all_sets = {(m, k): [] for m in SELECTORS for k in cfg.k_values}
    frequency_ranks = {(m, k): np.zeros(X.shape[1], dtype=float) for m in SELECTORS for k in cfg.k_values}
    selected_path = output / "selected_features_by_subsample.csv"
    temporary = selected_path.with_suffix(".tmp.csv")
    first = True
    for sid, (train, omitted) in enumerate(subsamples, 1):
        assert len(train) == 512 and len(set(train)) == 512 and not set(train) & set(omitted)
        assert not set(ids[train]) & set(data.reserved_test_ids)
        indices.extend({"subsample_id": sid, "sample_position_in_subsample": pos + 1, "sample_id": ids[idx],
                        "development_position": int(idx), "cancer_type": y[idx], "seed": 42}
                       for pos, idx in enumerate(train))
        checkpoint = output / "checkpoints" / f"subsample_{sid:02d}"
        existing = load_checkpoint(checkpoint, identity)
        if existing is None:
            raw, labels = X[train], y[train]
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg.numeric_threads):
                warnings.simplefilter("always")
                variance, manual_f, constant = raw_training_statistics(raw, labels)
                f, _ = f_classif(raw, labels)
                validate_anova(f, manual_f, constant)
                model = build_pipeline(cfg, "full_svm", 20531)
                scaler, svc = model.named_steps["scale"], model.named_steps["model"]
                with patch.object(scaler, "fit", wraps=scaler.fit) as sf, patch.object(svc, "fit", wraps=svc.fit) as mf:
                    start = time.perf_counter()
                    model.fit(raw, labels)
                    seconds = time.perf_counter() - start
                    assert sf.call_count == mf.call_count == 1
                    np.testing.assert_array_equal(sf.call_args.args[0], raw)
                    np.testing.assert_array_equal(mf.call_args.args[1], labels)
                    np.testing.assert_allclose(mf.call_args.args[0], scaler.transform(raw), rtol=1e-12, atol=1e-12)
                np.testing.assert_allclose(scaler.mean_, raw.mean(axis=0), rtol=1e-11, atol=1e-12)
                np.testing.assert_allclose(scaler.var_, raw.var(axis=0), rtol=1e-10, atol=1e-12)
                assert np.all(np.asarray(scaler.n_samples_seen_) == 512) and svc.n_features_in_ == 20531
                importance = np.linalg.norm(svc.coef_, ord=2, axis=0)
                assert importance.shape == (20531,) and np.isfinite(importance).all()
                ranked = {"variance": rank_scores(variance, "variance"), "anova": rank_scores(f, "anova"),
                          "svc_l2": rank_scores(importance, "svc_l2")}
                assert not any(constant[ranked[m][:max(cfg.k_values)]].any() for m in SELECTORS)
            captured = [{"subsample_id": sid, "category": w.category.__name__, "message": str(w.message)} for w in caught]
            if any(issubclass(w.category, ConvergenceWarning) for w in caught):
                atomic_json(checkpoint.with_suffix(".failure.json"), {"warnings": captured})
                raise RuntimeError(f"系数法子采样 {sid} 未收敛，保留已有断点并停止")
            audit = {"subsample_id": sid, "n_samples": 512, "n_features": 20531, "reserved_test_overlap": 0,
                     "scaler_samples": 512, "scaler_fit_audit_passed": True, "fit_input_matches_subsample": True,
                     "scaler_fit_calls": 1, "classifier_fit_calls": 1, "coefficient_importance": "L2_norm_across_classes",
                     "anova_matches_independent_training_calculation": True, "n_constant_genes": int(constant.sum()),
                     "n_undefined_anova_scores": int(np.isnan(f).sum()), "n_infinite_anova_scores": 0,
                     "coefficient_model_fit_seconds": seconds, "max_solver_iterations": int(np.max(np.atleast_1d(svc.n_iter_))),
                     "class_counts": ";".join(f"{c}:{int((labels == c).sum())}" for c in CLASS_ORDER), "convergence_warning_count": 0}
            save_checkpoint(checkpoint, {"identity": identity, "audit": audit, "warnings": captured},
                            train_indices=train, omitted_indices=omitted, variance=variance, anova=f, svc_l2=importance,
                            variance_rank=ranked["variance"], anova_rank=ranked["anova"], svc_l2_rank=ranked["svc_l2"],
                            coefficients=svc.coef_, scaler_mean=scaler.mean_, scaler_variance=scaler.var_)
            record, arrays = load_checkpoint(checkpoint, identity)
            log(f"RQ2 共享子采样 {sid}/30 完成；系数模型拟合 {seconds:.2f}s；常数基因 {constant.sum()}")
        else:
            record, arrays = existing
            log(f"RQ2 共享子采样 {sid}/30 复用有效断点")
        np.testing.assert_array_equal(arrays["train_indices"], train)
        np.testing.assert_array_equal(arrays["omitted_indices"], omitted)
        np.testing.assert_allclose(arrays["svc_l2"], np.linalg.norm(arrays["coefficients"], axis=0), rtol=1e-12, atol=1e-12)
        audits.append(record["audit"])
        warning_rows.extend(record["warnings"])
        for method in SELECTORS:
            ranking = arrays[method + "_rank"]
            assert len(ranking) == len(set(ranking)) == 20531
            for k in cfg.k_values:
                selected = ranking[:k]
                assert np.isfinite(arrays[method][selected]).all()
                all_sets[(method, k)].append(set(selected.tolist()))
                frequency_ranks[(method, k)][selected] += np.arange(1, k + 1)
                table = pd.DataFrame({"method": method, "k": k, "subsample_id": sid,
                                      "selection_rank": np.arange(1, k + 1), "original_column_index": selected,
                                      "gene_id": genes[selected], "selector_score": arrays[method][selected]})
                table.to_csv(temporary, mode="w" if first else "a", header=first, index=False,
                             encoding="utf-8-sig" if first else "utf-8")
                first = False
        # 每个子采样已有独立原子断点；中断后无需重训该模型。
        atomic_json(output / "progress.json", {"completed_subsamples": sid, "expected_subsamples": 30})
    temporary.replace(selected_path)
    save(pd.DataFrame(indices), output / "subsample_indices.csv")
    save(pd.DataFrame(audits), output / "subsample_fit_audit.csv")
    save(pd.DataFrame(warning_rows, columns=["subsample_id", "category", "message"]), output / "warnings.csv")
    pairs, summaries, frequencies, cross = [], [], [], []
    p = X.shape[1]
    for method in SELECTORS:
        for k in cfg.k_values:
            sets = all_sets[(method, k)]
            assert len(sets) == 30 and all(len(s) == k for s in sets)
            current = []
            for a, b in itertools.combinations(range(30), 2):
                overlap = len(sets[a] & sets[b])
                row = {"method": method, "k": k, "subsample_a": a + 1, "subsample_b": b + 1,
                       "overlap": overlap, "jaccard": overlap / (2 * k - overlap),
                       "kuncheva": (overlap - k * k / p) / (k - k * k / p)}
                pairs.append(row)
                current.append(row)
            assert len(current) == 435
            counts = np.zeros(p, dtype=int)
            for s in sets:
                counts[list(s)] += 1
            rank_sum = frequency_ranks[(method, k)]
            mean_rank = np.divide(rank_sum, counts, out=np.full(p, np.nan), where=counts > 0)
            frequencies.append(pd.DataFrame({"method": method, "k": k, "original_column_index": np.arange(p), "gene_id": genes,
                                             "selection_count": counts, "selection_frequency": counts / 30,
                                             "mean_rank_when_selected": mean_rank, "n_subsamples": 30}))
            frame = pd.DataFrame(current)
            summaries.append({"method": method, "k": k, "n_sets": 30, "n_pairs": 435,
                              "n_always_selected": int((counts == 30).sum()), "n_ever_selected": int((counts > 0).sum()),
                              **{f"jaccard_{key}": value for key, value in descriptive(frame.jaccard).items() if key != "n"},
                              **{f"kuncheva_{key}": value for key, value in descriptive(frame.kuncheva).items() if key != "n"},
                              "expected_random_overlap": k * k / p,
                              "chance_correction_note": "Kuncheva equal-size correction; descriptive, not independent pairs"})
    for k in cfg.k_values:
        for a, b in itertools.combinations(SELECTORS, 2):
            for sid in range(30):
                overlap = len(all_sets[(a, k)][sid] & all_sets[(b, k)][sid])
                cross.append({"method_a": a, "method_b": b, "k": k, "subsample_id": sid + 1,
                              "overlap": overlap, "jaccard": overlap / (2 * k - overlap)})
    save(pd.DataFrame(pairs), output / "stability_pairwise_jaccard.csv")
    save(pd.DataFrame(summaries), output / "stability_summary.csv")
    save(pd.concat(frequencies, ignore_index=True), output / "feature_selection_frequency.csv")
    save(pd.DataFrame(cross), output / "cross_method_jaccard.csv")
    atomic_json(output / "protocol.json", {"n_subsamples": 30, "n_subsample_samples": 512, "seed": 42,
                "n_pairs_each_method_k": 435, "coefficient_models_fitted": 30,
                "score_ranking_fits_per_subsample": 1, "same_subsample_for_all_methods_and_k": True,
                "constant_anova_strategy": "actual scores retained as NaN; ranking copy uses -inf; unexpected NaN/Inf stops run",
                "ties": "variance/SVC original position ascending; ANOVA matches SelectKBest stable ascending then take last K",
                "not_performance_evaluation_of_selected_coefficient_features": True,
                "pairwise_dependence": "all pairs correlated; descriptive only; no conventional CIs or independent-sample tests"})
    log("RQ2 完成：18 组稳定性配置，各 435 次比较；30 个系数模型，没有另做筛选后分类评分。")
