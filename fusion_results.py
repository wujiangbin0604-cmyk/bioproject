# -*- coding: utf-8 -*-
"""融合实验真实断点聚合、共享子采样稳定性；不接触保留测试行。"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from ablation_engine import METRICS, atomic_json, load_checkpoint, read_json, scores
from ablation_results import class_metrics, save
from config import CLASS_ORDER
from fusion_selection import choose_features, prepare_scores, schemes
from repeated_cv import descriptive


def statistics(values, prefix):
    values = pd.Series(values).dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return {prefix + s: None for s in ("mean", "std", "min", "max", "median", "p05", "p95")}
    return {prefix + s: value for s, value in descriptive(values).items() if s != "n"}


def aggregate(run, data, identity):
    definitions = read_json(run / "cv_fold_indices.json")["folds"]
    details, audits, predictions, perclass, matrices, warnings = [], [], [], [], [], []
    feature_file = run / "fusion_selected_features.csv"
    temp, first = feature_file.with_suffix(".tmp.csv"), True
    overlap, score_diagnostics, score_warnings = [], [], []
    genes = data.X.columns.to_numpy(dtype=str)
    for e in range(1, 101):
        diagnostic, c = load_checkpoint(run / "scores_cv" / f"fold_{e:03d}", identity)
        score_diagnostics.append({"evaluation_id": e, "n_samples": diagnostic["n_samples"], "n_features": diagnostic["n_features"],
                                  "n_constant": diagnostic["n_constant"], "anova_nan_count": diagnostic["anova_nan_count"],
                                  "anova_inf_count": diagnostic["anova_inf_count"], "independent_score_audit_passed": diagnostic["independent_score_audit_passed"],
                                  "training_digest": diagnostic["training_digest"]})
        score_warnings.extend({"evaluation_id": e, **w} for w in diagnostic["warnings"])
        for k in (20, 50):
            a, b = set(c["anova_rank"][:k]), set(c["variance_rank"][:k])
            overlap.append({"evaluation_id": e, "repeat_id": (e - 1) // 5 + 1, "fold_id": (e - 1) % 5 + 1, "k": k,
                            "anova_size": k, "variance_size": k, "intersection_size": len(a & b), "union_size": len(a | b),
                            "anova_only_size": len(a - b), "variance_only_size": len(b - a), "jaccard": len(a & b) / len(a | b)})
    for s in schemes():
        for e, definition in enumerate(definitions, 1):
            record, arrays = load_checkpoint(run / "checkpoints" / f"{s.name}_{e:03d}", identity)
            row = record["metrics"]
            assert row["scheme"] == s.name and row["evaluation_id"] == e
            details.append(row)
            audits.append(record["audit"])
            warnings.extend({"scheme": s.name, "evaluation_id": e, **w} for w in record["warnings"])
            selected = arrays["selected"]
            assert len(selected) == len(set(selected)) == row["n_features"]
            common = {"scheme": s.name, "rule": s.rule, "k": s.k, "increment": s.increment,
                      "evaluation_id": e, "repeat_id": (e - 1) // 5 + 1, "fold_id": (e - 1) % 5 + 1, "n_features": len(selected)}
            if len(selected):
                f = pd.DataFrame({**common, "gene_id": genes[selected], "original_column_index": selected,
                                  "anova_score": arrays["anova_score"], "variance": arrays["variance"],
                                  "anova_rank": arrays["anova_rank"], "variance_rank": arrays["variance_rank"]})
                f.to_csv(temp, mode="w" if first else "a", index=False, header=first, encoding="utf-8-sig" if first else "utf-8")
                first = False
            if row["status"] == "skipped_empty":
                assert len(selected) == 0 and len(arrays["valid_pred"]) == 0
                continue
            valid_ids, train_ids = definition["validation_sample_ids"], definition["train_sample_ids"]
            for part, ids, pred in (("train", train_ids, arrays["train_pred"]), ("validation", valid_ids, arrays["valid_pred"])):
                for metric, value in scores(data.y.loc[ids], pred).items():
                    np.testing.assert_allclose(row[f"{part}_{metric}"], value, rtol=1e-12, atol=1e-12)
            frame = pd.DataFrame({**common, "sample_id": valid_ids, "y_true": data.y.loc[valid_ids].to_numpy(), "y_pred": arrays["valid_pred"]})
            frame["is_error"] = frame.y_true.ne(frame.y_pred)
            predictions.append(frame)
            perclass.extend(class_metrics(frame.y_true, frame.y_pred, {**common, "level": "validation_fold"}))
            matrix = confusion_matrix(frame.y_true, frame.y_pred, labels=list(CLASS_ORDER))
            matrices.extend({**common, "level": "validation_fold", "true_label": a, "predicted_label": b, "count": int(matrix[i, j])}
                            for i, a in enumerate(CLASS_ORDER) for j, b in enumerate(CLASS_ORDER))
    if not first:
        temp.replace(feature_file)
    fold = pd.DataFrame(details)
    oof = pd.concat(predictions, ignore_index=True)
    rounds, summaries = [], []
    for s in schemes():
        sub = fold.loc[fold.scheme.eq(s.name)]
        assert len(sub) == 100
        for r in range(1, 21):
            p = oof.loc[oof.scheme.eq(s.name) & oof.repeat_id.eq(r)]
            complete = len(p) == p.sample_id.nunique() == 640
            common = {"scheme": s.name, "rule": s.rule, "k": s.k, "increment": s.increment, "repeat_id": r}
            row = {**common, "status": "complete" if complete else "incomplete_empty", "n_oof_samples": len(p), "n_missing_oof_samples": 640 - len(p)}
            row.update({f"oof_{m}": v for m, v in scores(p.y_true, p.y_pred).items()} if complete else {f"oof_{m}": None for m in METRICS})
            row["error_count"] = int(p.is_error.sum()) if complete else None
            rounds.append(row)
            if complete:
                perclass.extend(class_metrics(p.y_true, p.y_pred, {**common, "evaluation_id": 0, "fold_id": 0, "n_features": None, "level": "round_oof"}))
                matrix = confusion_matrix(p.y_true, p.y_pred, labels=list(CLASS_ORDER))
                matrices.extend({**common, "evaluation_id": 0, "fold_id": 0, "n_features": None, "level": "round_oof", "true_label": a, "predicted_label": b, "count": int(matrix[i, j])}
                                for i, a in enumerate(CLASS_ORDER) for j, b in enumerate(CLASS_ORDER))
        valid = sub.loc[sub.status.eq("evaluated")]
        row = {"scheme": s.name, "rule": s.rule, "k": s.k, "increment": s.increment, "experiment": s.experiment,
               "fixed_budget": s.fixed_budget, "n_expected_folds": 100, "n_evaluated_folds": len(valid), "n_empty_folds": int(sub.status.eq("skipped_empty").sum())}
        for c in [f"{prefix}_{m}" for prefix in ("train", "validation", "gap") for m in METRICS] + ["fit_seconds", "predict_seconds"]:
            row.update(statistics(valid[c], c + "_"))
        row.update(statistics(sub.n_features, "n_features_"))
        summaries.append(row)
    round_table = pd.DataFrame(rounds)
    for row in summaries:
        sub = round_table.loc[round_table.scheme.eq(row["scheme"]) & round_table.status.eq("complete")]
        row["n_complete_oof_rounds"] = len(sub)
        for m in METRICS:
            row.update(statistics(sub[f"oof_{m}"], f"oof_{m}_"))
    error_frequency = oof.groupby(["scheme", "sample_id", "y_true"]).is_error.agg(error_count="sum", n_predictions="size").reset_index()
    error_frequency["error_rate"] = error_frequency.error_count / error_frequency.n_predictions
    error_frequency["expected_predictions"] = 20
    for filename, frame in (("fusion_cv_fold_results.csv", fold), ("fusion_cv_round_results.csv", round_table),
                             ("fusion_cv_summary.csv", pd.DataFrame(summaries)), ("fusion_oof_predictions.csv", oof),
                             ("fusion_per_class_metrics.csv", pd.DataFrame(perclass)), ("fusion_confusion_matrices.csv", pd.DataFrame(matrices)),
                             ("fusion_fit_audit.csv", pd.DataFrame(audits)), ("fusion_feature_overlap.csv", pd.DataFrame(overlap)),
                             ("fusion_sample_errors.csv", error_frequency), ("fusion_error_predictions.csv", oof.loc[oof.is_error]),
                             ("fusion_score_diagnostics.csv", pd.DataFrame(score_diagnostics)),
                             ("fusion_score_warnings.csv", pd.DataFrame(score_warnings)),
                             ("fusion_warnings.csv", pd.DataFrame(warnings, columns=["scheme", "evaluation_id", "category", "message"]))):
        save(frame, run / filename)
    atomic_json(run / "classification_status.json", {"status": "complete", "n_scheme_fold_records": len(fold), "n_evaluated": int(fold.status.eq("evaluated").sum()),
                "n_empty": int(fold.status.eq("skipped_empty").sum()), "n_prior_fits_reused": int(fold.result_origin.eq("verified_prior_fit").sum()),
                "n_new_classifier_fits": int((fold.result_origin.eq("new_fit") & fold.status.eq("evaluated")).sum())})


def stability_analysis(run, parent, data, identity, log):
    """复用原30组索引，重新在每个子样本计算两种排名；不拟合分类器。"""
    indices = pd.read_csv(parent / "stability" / "subsample_indices.csv")
    assert set(indices.subsample_id) == set(range(1, 31))
    assert not set(indices.sample_id) & set(data.reserved_test_ids)
    save(indices, run / "stability" / "subsample_indices.csv")
    selected_schemes = [s for s in schemes() if s.experiment in ("A", "B")]
    all_sets = {s.name: [] for s in selected_schemes}
    selected_rows, audit_rows = [], []
    for sid, group in indices.groupby("subsample_id", sort=True):
        group = group.sort_values("sample_position_in_subsample")
        assert len(group) == group.sample_id.nunique() == 512
        names = group.sample_id.tolist()
        X, y = data.X.loc[names].to_numpy(dtype=float), data.y.loc[names].to_numpy(dtype=str)
        record, arrays = prepare_scores(X, y, run / "scores_subsamples" / f"subsample_{sid:02d}", identity, names)
        audit_rows.append({"subsample_id": int(sid), "n_samples": 512, "n_features": 20531, "scores_independently_audited": record["independent_score_audit_passed"],
                           "n_constant_genes": record["n_constant"], "anova_nan_count": record["anova_nan_count"], "anova_inf_count": record["anova_inf_count"],
                           "reserved_test_overlap": 0, "training_digest": record["training_digest"]})
        for s in selected_schemes:
            chosen = choose_features(arrays["anova_rank"], arrays["variance_rank"], s.rule, s.k, s.increment)
            all_sets[s.name].append(set(chosen.tolist()))
            selected_rows.extend({"scheme": s.name, "rule": s.rule, "k": s.k, "fixed_budget": s.fixed_budget, "subsample_id": int(sid),
                                  "gene_id": data.X.columns[g], "original_column_index": int(g)} for g in chosen)
        log(f"稳定性子采样 {sid}/30：原索引已核对，训练范围评分重新计算/校验，22个集合已构建。")
    pairs, summary, frequencies, overlaps = [], [], [], []
    for s in selected_schemes:
        sets = all_sets[s.name]
        assert len(sets) == 30
        values = []
        for i, j in itertools.combinations(range(30), 2):
            union = sets[i] | sets[j]
            # 空-空集合的Jaccard没有分类意义，明确记未定义，不冒充1。
            value = len(sets[i] & sets[j]) / len(union) if union else np.nan
            values.append(value)
            pairs.append({"scheme": s.name, "rule": s.rule, "k": s.k, "fixed_budget": s.fixed_budget,
                          "subsample_a": i + 1, "subsample_b": j + 1, "size_a": len(sets[i]), "size_b": len(sets[j]),
                          "intersection": len(sets[i] & sets[j]), "jaccard": value})
        counts = np.zeros(20531, dtype=int)
        for selected in sets:
            counts[list(selected)] += 1
        frequencies.append(pd.DataFrame({"scheme": s.name, "rule": s.rule, "k": s.k, "fixed_budget": s.fixed_budget,
                                        "gene_id": data.X.columns, "original_column_index": np.arange(20531),
                                        "selection_count": counts, "selection_frequency": counts / 30, "n_subsamples": 30}))
        summary.append({"scheme": s.name, "rule": s.rule, "k": s.k, "fixed_budget": s.fixed_budget,
                        "n_sets": 30, "n_pairs": 435, "n_defined_pairs": int(np.isfinite(values).sum()),
                        "n_empty_sets": sum(len(x) == 0 for x in sets), "n_always_selected": int((counts == 30).sum()),
                        "n_ever_selected": int((counts > 0).sum()), **statistics(values, "jaccard_"),
                        **statistics([len(x) for x in sets], "set_size_")})
        for baseline in (f"anova_k{s.k}", f"variance_k{s.k}"):
            if baseline == s.name:
                continue
            for sid in range(30):
                a, b = sets[sid], all_sets[baseline][sid]
                overlaps.append({"scheme": s.name, "reference": baseline, "k": s.k, "subsample_id": sid + 1,
                                 "overlap_count": len(a & b), "jaccard": len(a & b) / len(a | b) if a | b else np.nan})
    save(pd.DataFrame(summary), run / "fusion_feature_stability.csv")
    save(pd.concat(frequencies, ignore_index=True), run / "fusion_feature_frequency.csv")
    save(pd.DataFrame(pairs), run / "stability" / "pairwise_jaccard.csv")
    save(pd.DataFrame(selected_rows), run / "stability" / "selected_features_by_subsample.csv")
    save(pd.DataFrame(overlaps), run / "stability" / "overlap_with_single_methods.csv")
    save(pd.DataFrame(audit_rows), run / "stability" / "fit_audit.csv")
    atomic_json(run / "stability" / "protocol.json", {"indices_reused_from": str(parent / "stability" / "subsample_indices.csv"),
                "n_subsamples": 30, "n_subsample_samples": 512, "rankings_recomputed_within_each_subsample": True,
                "classifier_models_fitted": 0, "n_schemes": len(selected_schemes), "n_pairs_per_scheme": 435,
                "empty_empty_jaccard": "undefined", "variable_budget_schemes_reported_separately": True,
                "statistical_inference": "descriptive only; dependent pairs; no independent-sample tests"})
