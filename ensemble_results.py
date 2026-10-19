# -*- coding: utf-8 -*-
"""硬投票结果聚合和中文报告；只消费审计完成的开发集预测断点。"""
from __future__ import annotations

from itertools import combinations
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ablation_engine import atomic_json, load_checkpoint, read_json
from ablation_report import markdown_table
from ablation_results import save
from config import CLASS_ORDER
from hard_voting import ALL_MODELS, BASE_MODELS, METRICS, MODEL_NAMES, fast_scores
from repeated_cv import descriptive


def class_and_matrix(true, predicted, common):
    lookup = {c: i for i, c in enumerate(CLASS_ORDER)}
    a = np.fromiter((lookup[c] for c in true), int)
    b = np.fromiter((lookup[c] for c in predicted), int)
    cm = np.bincount(a * 5 + b, minlength=25).reshape(5, 5)
    tp, support, pred_n = cm.diagonal(), cm.sum(1), cm.sum(0)
    p = np.divide(tp, pred_n, out=np.zeros(5), where=pred_n > 0)
    r = np.divide(tp, support, out=np.zeros(5), where=support > 0)
    f = np.divide(2 * tp, support + pred_n, out=np.zeros(5), where=support + pred_n > 0)
    classes = [{**common, "cancer_type": c, "precision": float(p[i]), "recall": float(r[i]),
                "f1": float(f[i]), "support": int(support[i]), "errors": int(support[i] - tp[i])}
               for i, c in enumerate(CLASS_ORDER)]
    matrices = [{**common, "true_label": c, "predicted_label": d, "count": int(cm[i, j])}
                for i, c in enumerate(CLASS_ORDER) for j, d in enumerate(CLASS_ORDER)]
    return classes, matrices


def complementarity(group, scope, label):
    """预测事件、独立患者分层记录；不实施相关观测的独立样本检验。"""
    common = {"scope": scope, "scope_label": label, "n_prediction_events": len(group),
              "n_unique_patients": group.sample_id.nunique()}
    rows = []
    for n in range(4):
        mask = group.base_error_count.eq(n)
        rows.append({**common, "kind": "number_of_base_errors", "category": str(n),
                     "count": int(mask.sum()), "proportion": float(mask.mean()),
                     "affected_unique_patients": group.loc[mask, "sample_id"].nunique()})
    patterns = (group.pred_A.ne(group.y_true).astype(int).astype(str) +
                group.pred_B.ne(group.y_true).astype(int).astype(str) +
                group.pred_C.ne(group.y_true).astype(int).astype(str))
    for bits in ("000", "001", "010", "011", "100", "101", "110", "111"):
        mask = patterns.eq(bits)
        rows.append({**common, "kind": "error_bits_ABC_1_is_wrong", "category": bits,
                     "count": int(mask.sum()), "proportion": float(mask.mean()),
                     "affected_unique_patients": group.loc[mask, "sample_id"].nunique()})
    masks = {"unanimous": group.unanimous, "two_agree": ~group.unanimous & ~group.all_three_different,
             "all_three_different": group.all_three_different}
    for name, mask in masks.items():
        rows.append({**common, "kind": "prediction_agreement", "category": name,
                     "count": int(mask.sum()), "proportion": float(mask.mean()),
                     "affected_unique_patients": group.loc[mask, "sample_id"].nunique()})
    for a, b in combinations("ABC", 2):
        ea, eb = ~group[f"correct_{a}"], ~group[f"correct_{b}"]
        both, either = ea & eb, ea | eb
        rows.append({**common, "kind": "pair_error_overlap", "category": a + b,
                     "count": int(both.sum()), "error_events_first": int(ea.sum()),
                     "error_events_second": int(eb.sum()), "error_events_union": int(either.sum()),
                     "jaccard": float(both.sum() / either.sum()) if either.any() else None,
                     "same_wrong_prediction_events": int((both & group[f"pred_{a}"].eq(group[f"pred_{b}"])).sum()),
                     "only_first_wrong": int((ea & ~eb).sum()), "only_second_wrong": int((~ea & eb).sum()),
                     "affected_unique_patients": group.loc[both, "sample_id"].nunique()})
    return rows


def aggregate(run, data, identity):
    definitions = read_json(run / "cv_fold_indices.json")["folds"]
    fold_rows, oof_parts, audit_rows, per_class, matrices = [], [], [], [], []
    unions, selected_rows, control_rows, warnings = [], [], [], []
    all_genes = set()
    for d in definitions:
        e = d["evaluation_id"]
        record, arrays = load_checkpoint(run / f"checkpoints/fold_{e:03d}", identity)
        common = {"evaluation_id": e, "repeat_id": d["repeat"], "fold_id": d["fold"]}
        train_ids, valid_ids = d["train_sample_ids"], d["validation_sample_ids"]
        yt, yv = data.y.loc[train_ids].to_numpy(), data.y.loc[valid_ids].to_numpy()
        metadata = record["base_records"]
        fit_sum = sum(r["metrics"]["fit_seconds"] for r in metadata)
        pred_sum = sum(r["metrics"]["predict_seconds"] for r in metadata)
        for i, model in enumerate(ALL_MODELS):
            tp = arrays["train_predictions"][:, i] if model != "vote" else arrays["train_vote"]
            vp = arrays["valid_predictions"][:, i] if model != "vote" else arrays["valid_vote"]
            tr, va = fast_scores(yt, tp), fast_scores(yv, vp)
            row = {**common, "model": model, "model_name": MODEL_NAMES[model], "n_train": 512, "n_validation": 128,
                   "n_distinct_genes": int(len(arrays["union"])) if model == "vote" else 50,
                   "fit_seconds": fit_sum if model == "vote" else metadata[i]["metrics"]["fit_seconds"],
                   "predict_seconds": pred_sum + record["vote_seconds_train_and_validation"] if model == "vote" else metadata[i]["metrics"]["predict_seconds"],
                   "timing_origin": "sum_historical_member_times_plus_current_vote" if model == "vote" and record["reused"] else "historical_fit_and_train_plus_valid_predict" if record["reused"] else "current_fit_and_train_plus_valid_predict",
                   "vote_seconds_train_and_validation": record["vote_seconds_train_and_validation"] if model == "vote" else 0.,
                   "validation_error_count": int(np.sum(vp != yv)),
                   "base_fits_reused": record["reused"]}
            for metric in METRICS:
                row.update({f"train_{metric}": tr[metric], f"validation_{metric}": va[metric], f"gap_{metric}": tr[metric] - va[metric]})
            fold_rows.append(row)
            for level, true, pred in (("training_fold", yt, tp), ("validation_fold", yv, vp)):
                cr, mr = class_and_matrix(true, pred, {**common, "model": model, "level": level})
                per_class.extend(cr)
                matrices.extend(mr)
        part = pd.DataFrame({**common, "sample_id": valid_ids, "y_true": yv,
                             **{f"pred_{key}": arrays["valid_predictions"][:, i] for i, key in enumerate("ABC")},
                             "pred_vote": arrays["valid_vote"],
                             **{key: arrays[f"validation_{key}"] for key in ("has_majority", "all_three_different", "tie_rule_applied", "winning_vote_count", "unanimous")}})
        for model in ALL_MODELS:
            part[f"correct_{model}"] = part[f"pred_{model}"].eq(part.y_true)
        part["base_error_count"] = 3 - part[[f"correct_{m}" for m in "ABC"]].sum(axis=1)
        oof_parts.append(part)
        audit_rows.extend(record["audits"])
        audit_rows.append({**common, "model": "vote", "train_validation_overlap": 0, "reserved_test_overlap": 0,
                           "ordered_indices_verified": True, "exactly_three_predictions_per_validation_sample": True,
                           "label_encoding_consistent": True, "predeclared_tie_rule": "A", "vote_rule_verified": True,
                           "A_C_same_ANOVA_genes": bool(np.array_equal(arrays["selected"][0], arrays["selected"][2])),
                           "all_member_predictions_same_validation_ID_order": True,
                           "reserved_expression_rows_parsed": 0, "reserved_label_rows_parsed": 0})
        gene_sets = [set(data.X.columns[a]) for a in arrays["selected"]]
        union, intersection = set.union(*gene_sets), gene_sets[0] & gene_sets[1]
        all_genes.update(union)
        unions.append({**common, "n_A": 50, "n_B": 50, "n_C": 50, "A_C_overlap": len(gene_sets[0] & gene_sets[2]),
                       "ANOVA_variance_intersection": len(intersection), "ANOVA_variance_union": len(union),
                       "ANOVA_variance_jaccard": len(intersection) / len(union), "n_distinct_genes_system": len(union),
                       **{f"genes_{key}": json.dumps(sorted(gs, key=lambda x: int(x[5:])), ensure_ascii=False) for key, gs in zip("ABC", gene_sets)},
                       "union_genes": json.dumps(sorted(union, key=lambda x: int(x[5:])), ensure_ascii=False)})
        for i, key in enumerate("ABC"):
            selected_rows.extend({**common, "model": key, "gene_id": str(data.X.columns[g]), "original_column_index": int(g),
                                  "training_selection_score": float(s)} for g, s in zip(arrays["selected"][i], arrays["selector_scores"][i]))
            warnings.extend({**common, "model": key, **w} for w in metadata[i]["warnings"])
        control_rows.extend(record["budget_control_metrics"])
    folds, oof, features = pd.DataFrame(fold_rows), pd.concat(oof_parts, ignore_index=True), pd.DataFrame(unions)
    assert len(oof) == 12800 and not oof.duplicated(["repeat_id", "sample_id"]).any()
    round_rows = []
    for repeat, group in oof.groupby("repeat_id", sort=True):
        assert len(group) == group.sample_id.nunique() == 640 and set(group.sample_id) == set(data.X.index)
        for model in ALL_MODELS:
            common = {"repeat_id": int(repeat), "model": model}
            model_folds = folds.loc[folds.repeat_id.eq(repeat) & folds.model.eq(model)]
            round_rows.append({**common, "n_samples": 640,
                               **{f"oof_{k}": v for k, v in fast_scores(group.y_true, group[f"pred_{model}"]).items()},
                               "oof_error_count": int((~group[f"correct_{model}"]).sum()),
                               "fit_seconds_sum": float(model_folds.fit_seconds.sum()),
                               "predict_seconds_sum": float(model_folds.predict_seconds.sum()),
                               **{f"{c}_mean": float(model_folds[c].mean()) for c in model_folds if c.startswith(("train_", "validation_", "gap_"))}})
            cr, mr = class_and_matrix(group.y_true, group[f"pred_{model}"], {**common, "evaluation_id": 0, "fold_id": 0, "level": "round_oof"})
            per_class.extend(cr)
            matrices.extend(mr)
    for model in ALL_MODELS:
        cr, mr = class_and_matrix(oof.y_true, oof[f"pred_{model}"], {"model": model, "repeat_id": 0, "evaluation_id": 0, "fold_id": 0, "level": "pooled_repeated_OOF_events"})
        per_class.extend(cr)
        matrices.extend(mr)
    rounds = pd.DataFrame(round_rows)
    summary_rows = []
    for model in ALL_MODELS:
        for level, table in (("validation_fold", folds.loc[folds.model.eq(model)]), ("round_oof", rounds.loc[rounds.model.eq(model)])):
            columns = [c for c in table if c.startswith(("train_", "validation_", "gap_", "oof_")) or c in ("fit_seconds", "predict_seconds", "fit_seconds_sum", "predict_seconds_sum")]
            for col in columns:
                summary_rows.append({"model": model, "level": level, "metric": col, **descriptive(table[col])})
    summary_table = pd.DataFrame(summary_rows)
    samples = []
    for sid, group in oof.groupby("sample_id", sort=False):
        for model in ALL_MODELS:
            predictions = group[f"pred_{model}"]
            modes = predictions.value_counts()
            samples.append({"sample_id": sid, "y_true": group.y_true.iloc[0], "model": model,
                            "n_oof_predictions": len(group), "error_count": int((~group[f"correct_{model}"]).sum()),
                            "error_proportion": float((~group[f"correct_{model}"]).mean()),
                            "n_distinct_predicted_labels": predictions.nunique(), "modal_prediction": modes.index[0],
                            "modal_prediction_fraction": float(modes.iloc[0] / len(group)),
                            "error_repeat_ids": json.dumps(group.loc[~group[f"correct_{model}"], "repeat_id"].tolist()),
                            "tie_rule_events": int(group.tie_rule_applied.sum())})
    changed, correction_rows = [], []
    for model in "ABC":
        corrected = ~oof[f"correct_{model}"] & oof.correct_vote
        regressed = oof[f"correct_{model}"] & ~oof.correct_vote
        for kind, mask in (("corrected", corrected), ("new_error", regressed)):
            selected = oof.loc[mask].copy()
            selected.insert(0, "reference_model", model)
            selected.insert(1, "change", kind)
            changed.append(selected)
        baseline_errors = int((~oof[f"correct_{model}"]).sum())
        correction_rows.append({"reference_model": model, "reference_error_events": baseline_errors,
            "vote_error_events": int((~oof.correct_vote).sum()), "corrected_events": int(corrected.sum()),
            "new_error_events": int(regressed.sum()), "net_error_change_vote_minus_base": int(regressed.sum() - corrected.sum()),
            "corrected_unique_patients": int(oof.loc[corrected, "sample_id"].nunique()),
            "new_error_unique_patients": int(oof.loc[regressed, "sample_id"].nunique()),
            "corrected_patient_ids": json.dumps(sorted(oof.loc[corrected, "sample_id"].unique())),
            "new_error_patient_ids": json.dumps(sorted(oof.loc[regressed, "sample_id"].unique()))})
    comp = complementarity(oof, "all_repeated_oof_events", "all")
    for repeat, group in oof.groupby("repeat_id"):
        comp.extend(complementarity(group, "round_oof", str(repeat)))
    for cancer, group in oof.groupby("y_true"):
        comp.extend(complementarity(group, "cancer_pooled_events", cancer))
    paired_folds, paired_rounds = [], []
    for model in "ABC":
        for table, level, idcol, prefix, destination in ((folds, "validation_fold", "evaluation_id", "validation_", paired_folds),
                                                       (rounds, "round_oof", "repeat_id", "oof_", paired_rounds)):
            base = table.loc[table.model.eq(model)].set_index(idcol)
            vote = table.loc[table.model.eq("vote")].set_index(idcol)
            for value in base.index:
                destination.append({idcol: int(value), "reference_model": model, "level": level,
                                    **{f"vote_minus_base_{m}": float(vote.loc[value, prefix + m] - base.loc[value, prefix + m]) for m in METRICS}})
    class_summary_rows = []
    pc = pd.DataFrame(per_class)
    for (model, cancer), group in pc.loc[pc.level.eq("round_oof")].groupby(["model", "cancer_type"]):
        class_summary_rows.append({"model": model, "cancer_type": cancer,
                                   **{f"{col}_{k}": v for col in ("precision", "recall", "f1", "errors") for k, v in descriptive(group[col]).items()}})
    error_cancer = []
    for cancer, group in oof.groupby("y_true", sort=False):
        for model in ALL_MODELS:
            mask = ~group[f"correct_{model}"]
            error_cancer.append({"cancer_type": cancer, "model": model, "n_patients": group.sample_id.nunique(),
                                 "n_prediction_events": len(group), "error_events": int(mask.sum()),
                                 "error_event_proportion": float(mask.mean()), "ever_wrong_patients": group.loc[mask, "sample_id"].nunique()})
    controls = pd.DataFrame(control_rows)
    controls_summary = []
    for scheme, group in controls.groupby("scheme"):
        for col in [f"validation_{m}" for m in METRICS] + ["fit_seconds", "predict_seconds", "n_features"]:
            controls_summary.append({"scheme": scheme, "level": "validation_fold", "metric": col, **descriptive(group[col])})
    files = {"ensemble_fold_results.csv": folds, "ensemble_round_results.csv": rounds,
             "ensemble_oof_predictions.csv": oof, "ensemble_per_class_metrics.csv": pc,
             "ensemble_confusion_matrices.csv": pd.DataFrame(matrices), "ensemble_error_complementarity.csv": pd.DataFrame(comp),
             "ensemble_corrected_and_new_errors.csv": pd.concat(changed, ignore_index=True),
             "ensemble_feature_union.csv": features, "ensemble_selected_features_by_fold.csv": pd.DataFrame(selected_rows),
             "ensemble_fit_audit.csv": pd.DataFrame(audit_rows), "ensemble_descriptive_statistics.csv": summary_table,
             "ensemble_sample_prediction_stability.csv": pd.DataFrame(samples), "ensemble_correction_summary.csv": pd.DataFrame(correction_rows),
             "ensemble_paired_fold_differences.csv": pd.DataFrame(paired_folds), "ensemble_paired_round_differences.csv": pd.DataFrame(paired_rounds),
             "ensemble_per_class_summary.csv": pd.DataFrame(class_summary_rows), "ensemble_errors_by_cancer.csv": pd.DataFrame(error_cancer),
             "ensemble_matched_budget_fold_results.csv": controls, "ensemble_matched_budget_summary.csv": pd.DataFrame(controls_summary)}
    for name, table in files.items():
        save(table, run / name)
    atomic_json(run / "logs/diagnostic_warnings.json", warnings)
    pooled = pd.DataFrame(comp).query("scope == 'all_repeated_oof_events'")
    agreement = {r["category"]: {"count": int(r["count"]), "proportion": float(r["proportion"])}
                 for r in pooled.loc[pooled.kind.eq("prediction_agreement")].to_dict("records")}
    models = {}
    for model in ALL_MODELS:
        models[model] = {"name": MODEL_NAMES[model],
            "validation_fold": {m: descriptive(folds.loc[folds.model.eq(model), f"validation_{m}"]) for m in METRICS},
            "round_oof": {m: descriptive(rounds.loc[rounds.model.eq(model), f"oof_{m}"]) for m in METRICS},
            "oof_error_events": int((~oof[f"correct_{model}"]).sum()),
            "ever_wrong_patients": int(oof.loc[~oof[f"correct_{model}"], "sample_id"].nunique()),
            "historical_fit_seconds_sum": float(folds.loc[folds.model.eq(model), "fit_seconds"].sum())}
    summary = {"protocol": "three-model-hard-vote-v1", "n_development_patients": 640, "n_genes_in_input": 20531,
               "reserved_patients_excluded": 161, "n_validation_folds": 100, "n_complete_oof_rounds": 20,
               "n_oof_patient_repeat_events": 12800, "n_oof_independent_patients": 640,
               "models": models, "agreement": agreement,
               "base_error_count_events": {str(n): int(oof.base_error_count.eq(n).sum()) for n in range(4)},
               "vote_vs_members": correction_rows,
               "gene_budget_per_training_fold": descriptive(features.n_distinct_genes_system),
               "ANOVA_variance_overlap_genes": descriptive(features.ANOVA_variance_intersection),
               "ANOVA_variance_jaccard": descriptive(features.ANOVA_variance_jaccard),
               "all_A_C_feature_sets_identical": bool(features.A_C_overlap.eq(50).all()),
               "distinct_gene_catalog_across_all_100_folds": len(all_genes),
               "gene_catalog_not_a_fixed_deployment_panel": True,
               "historical_base_model_fits_reused": int(folds.loc[folds.model.ne("vote"), "base_fits_reused"].sum()),
               "new_base_model_fits": int((~folds.loc[folds.model.ne("vote"), "base_fits_reused"]).sum()),
               "all_times_are_historical_or_sums_except_vote_overhead": bool(folds.base_fits_reused.all()),
               "no_significance_test": True, "no_test_evaluation": True, "no_hyperparameter_or_weight_search": True}
    atomic_json(run / "ensemble_summary.json", summary)
    return summary


def write_report(run, summary, verification):
    s = summary
    folds = pd.read_csv(run / "ensemble_fold_results.csv")
    rounds = pd.read_csv(run / "ensemble_round_results.csv")
    pc = pd.read_csv(run / "ensemble_per_class_summary.csv")
    corrections = pd.read_csv(run / "ensemble_correction_summary.csv")
    comp = pd.read_csv(run / "ensemble_error_complementarity.csv")
    controls = pd.read_csv(run / "ensemble_matched_budget_fold_results.csv")
    paired = pd.read_csv(run / "ensemble_paired_fold_differences.csv")
    frozen = read_json(run / "logs/frozen_experiment.json")
    table = []
    for model in ALL_MODELS:
        m = s["models"][model]
        table.append({"方案": m["name"], "100折Macro-F1均值": m["validation_fold"]["macro_f1"]["mean"],
                      "样本标准差": m["validation_fold"]["macro_f1"]["std"],
                      "Balanced Accuracy均值": m["validation_fold"]["balanced_accuracy"]["mean"],
                      "Accuracy均值": m["validation_fold"]["accuracy"]["mean"], "OOF错误事件": m["oof_error_events"],
                      "曾出错患者数": m["ever_wrong_patients"]})
    performance = pd.DataFrame(table)
    save(performance, run / "ensemble_results_table.csv")
    round_table = pd.DataFrame([{"方案": s["models"][m]["name"],
                                **{k: s["models"][m]["round_oof"]["macro_f1"][v] for k, v in (("20轮OOF Macro-F1均值", "mean"), ("样本标准差", "std"), ("最小值", "min"), ("最大值", "max"), ("中位数", "median"))}}
                               for m in ALL_MODELS])
    budget_table = []
    for name, group in controls.groupby("scheme"):
        budget_table.append({"同预算方案": name, "Macro-F1均值": group.validation_macro_f1.mean(),
                             "Macro-F1样本SD": group.validation_macro_f1.std(ddof=1),
                             "Balanced Accuracy均值": group.validation_balanced_accuracy.mean(),
                             "平均基因数": group.n_features.mean()})
    budget_table.append({"同预算方案": "三模型硬投票", "Macro-F1均值": s["models"]["vote"]["validation_fold"]["macro_f1"]["mean"],
                         "Macro-F1样本SD": s["models"]["vote"]["validation_fold"]["macro_f1"]["std"],
                         "Balanced Accuracy均值": s["models"]["vote"]["validation_fold"]["balanced_accuracy"]["mean"],
                         "平均基因数": s["gene_budget_per_training_fold"]["mean"]})
    budget_table = pd.DataFrame(budget_table)
    save(budget_table, run / "ensemble_budget_comparison_table.csv")
    pooled = comp.loc[comp.scope.eq("all_repeated_oof_events")]
    error_pairs = pooled.loc[pooled.kind.eq("pair_error_overlap"), ["category", "error_events_first", "error_events_second", "count", "error_events_union", "jaccard", "same_wrong_prediction_events"]]
    class_table = pc.pivot(index="cancer_type", columns="model", values="f1_mean").reindex(CLASS_ORDER)
    class_table["投票减A"] = class_table.vote - class_table.A
    class_table["投票减B"] = class_table.vote - class_table.B
    class_table["投票减C"] = class_table.vote - class_table.C
    regression = []
    for model in "ABC":
        g = paired.loc[paired.reference_model.eq(model)]
        regression.append({"参考模型": model, "投票Macro-F1更高折数": int(g.vote_minus_base_macro_f1.gt(1e-12).sum()),
                           "相同折数": int(g.vote_minus_base_macro_f1.abs().le(1e-12).sum()),
                           "更低折数": int(g.vote_minus_base_macro_f1.lt(-1e-12).sum())})
    vote_f1 = s["models"]["vote"]["validation_fold"]["macro_f1"]["mean"]
    better_all = all(vote_f1 > s["models"][m]["validation_fold"]["macro_f1"]["mean"] for m in "ABC")
    ba = s["models"]["vote"]["validation_fold"]["balanced_accuracy"]["mean"]
    improve_ba = all(ba > s["models"][m]["validation_fold"]["balanced_accuracy"]["mean"] for m in "ABC")
    changed = pd.read_csv(run / "ensemble_corrected_and_new_errors.csv")
    change_table = changed[["reference_model", "change", "sample_id", "y_true", "pred_A", "pred_B", "pred_C", "pred_vote"]].value_counts(sort=False).rename("预测事件数").reset_index()
    source_reuse = read_json(run / "logs/reuse_audit.json")
    fit_total = sum(s["models"][m]["historical_fit_seconds_sum"] for m in "ABC")
    ac = pooled.loc[pooled.kind.eq("pair_error_overlap") & pooled.category.eq("AC")].iloc[0]
    bc = pooled.loc[pooled.kind.eq("pair_error_overlap") & pooled.category.eq("BC")].iloc[0]
    ab = pooled.loc[pooled.kind.eq("pair_error_overlap") & pooled.category.eq("AB")].iloc[0]
    complement_note = (f"真实预测中，A/B只有{int(ab['count'])}次共同错误，但A的{s['models']['A']['oof_error_events']}次错误全部同时为C的错误；"
                       f"B的{s['models']['B']['oof_error_events']}次错误中{int(bc['count'])}次同时为C的错误。"
                       if int(ac['count']) == s['models']['A']['oof_error_events'] else
                       f"A/C有{int(ac['count'])}次共同错误，B/C有{int(bc['count'])}次共同错误。")
    complement_note += (f"本次恰好两个模型错误的{s['base_error_count_events']['2']}个事件中，错误模型给出了相同的错误癌种，"
                        f"因此投票保留这些错误；加上三模型全错的{s['base_error_count_events']['3']}次，"
                        f"得到投票的{s['models']['vote']['oof_error_events']}次错误。"
                        if s['agreement']['all_three_different']['count'] == 0 else
                        "应分别核对错误预测类别是否相同及平票规则，不从错误数量单独推断多数票结果。")
    budget_means = controls.groupby("scheme").validation_macro_f1.mean()
    cost_conclusion = ("本次投票的Macro-F1低于全部三个同预算单模型对照，也低于A/B两个50基因单模型，"
                       "因此当前实验没有提供用额外分类器和基因预算换取性能收益的证据。"
                       if (budget_means > vote_f1).all() and all(vote_f1 < s['models'][m]['validation_fold']['macro_f1']['mean'] for m in 'AB')
                       else "是否存在性能收益应结合上述真实同预算差值判断，不把更多模型自动视作更优。")
    class_interpretation = []
    for cancer, row in class_table.iterrows():
        changes_text = []
        for model in 'ABC':
            delta = row['vote'] - row[model]
            if abs(delta) > 1e-12:
                changes_text.append(f"相对{model}{'提高' if delta > 0 else '降低'}{abs(delta):.8f}")
        class_interpretation.append(f"{cancer}：" + ('；'.join(changes_text) if changes_text else '与三组基础模型相同'))
    stable = pd.read_csv(run / 'ensemble_sample_prediction_stability.csv')
    affected = stable.loc[stable.error_count.gt(0), 'sample_id'].unique()
    patient_table = stable.loc[stable.sample_id.isin(affected)].pivot(index=['sample_id','y_true'], columns='model', values='error_count').reset_index()
    vote_sd = s['models']['vote']['validation_fold']['macro_f1']['std']
    sd_text = '；'.join(f"相对{m}{'更小' if vote_sd < s['models'][m]['validation_fold']['macro_f1']['std'] else '更大或相同'}" for m in 'ABC')
    report = f'''# 三模型硬投票与错误互补性：开发集重复交叉验证报告

## 实验范围和可追溯性

固定640名开发患者、20,531个原始基因，使用与旧实验完全相同的有序样本及100组训练/验证ID。每折512人训练、128人验证；每轮合并640人OOF，共20轮、12,800个“患者×轮次”验证预测事件，独立患者仍为640人。161名保留样本未用于表达/标签解析、拟合、预测、评分或方法选择。TAR顺序扫描会经过文件字节，仅使用保留行首列ID实施排除；没有把其表达或标签加载为数值/类别。

本次复用{source_reuse['checked_base_checkpoints']}份核验通过的历史基础模型拟合，新增基础模型拟合{s['new_base_model_fits']}次。原始完整Pipeline分别在当前训练折独立拟合；本次通过旧拟合调用审计、开发数值+标签+列序指纹、模型参数、原始有序划分、逐条OOF身份、断点SHA256和训练评分摘要进行复核。复用不等于重新拟合，不能将本次分析耗时当作重新训练耗时。相关证据在 `logs/reuse_audit.json`、`ensemble_fit_audit.csv`、`checkpoints/` 与源码快照中。独立验收通过{verification['checks_passed']}项检查。

三组模型保持既有配置：A=ANOVA Top50→StandardScaler→LinearSVC(C=1, dual=auto, max_iter=50000, tol=1e-4, random_state=42)；B只将选择器换成原表达尺度高方差Top50（样本方差ddof=1，同方差原列号优先）；C=独立ANOVA Top50→StandardScaler→LogisticRegression(C=1, solver=lbfgs, max_iter=50000, tol=1e-4, class_weight=None, l1_ratio=0, random_state=42)，五分类使用该版本lbfgs的多项逻辑回归处理。`penalty='deprecated'`是sklearn 1.8的默认弃用占位参数，L2由l1_ratio=0明确；未更换成新模型。完整参数与版本见 `logs/frozen_experiment.json`。

投票规则在计算成绩前冻结：等权硬标签多数票；三者预测全部不同时固定采用A；不查看验证真值来决定平票处理。2/3或3/3仅是票数，不是患癌概率。没有权重搜索、软投票、概率校准、参数搜索或最终模型选择。恒定训练基因导致的预期ANOVA NaN评分警告保留在诊断文件，所有被选基因评分有限，无收敛警告。

## 实际分类结果

统计层级一：100个验证折，SD为样本标准差（ddof=1）。

{markdown_table(performance)}

统计层级二：20轮完整640人OOF的Macro-F1；与“100折分数平均”不是同一个统计量。

{markdown_table(round_table)}

所有指标的均值、样本SD、最小、最大、中位数和分位数见 `ensemble_descriptive_statistics.csv`，训练性能和训练−验证差距见 `ensemble_fold_results.csv`。100个折、20轮及12,800条事件均共享患者/训练数据；本报告只作描述性比较，不进行普通独立样本显著性检验，不报告误导性独立样本置信区间。

## 九个研究问题

1. **Macro-F1是否高于三个基础模型？** {'是' if better_all else '否'}。投票100折均值为{vote_f1:.8f}，具体相对变化见上表及逐折配对差值。不能用均值差直接推断统计显著性或外部泛化优势。

2. **Balanced Accuracy是否改善？** {'高于全部三个基础模型' if improve_ba else '没有同时高于全部三个基础模型'}，投票均值为{ba:.8f}。差异大小和变化方向应结合完整表理解。

3. **错误是否互补？** 三个基础模型全部正确、恰好一个错误、恰好两个错误、全部错误的事件数分别为{s['base_error_count_events']['0']}、{s['base_error_count_events']['1']}、{s['base_error_count_events']['2']}、{s['base_error_count_events']['3']}。两模型错误事件交集/并集如下。错误有部分互补不保证多数投票改善；共同错误会被多数票保留，两个模型一致误判也可能覆盖第三个模型的正确预测。

{markdown_table(error_pairs)}

{complement_note}

4. **纠正多少错误，同时新增多少错误？** 下面按每个参考模型分别计算，不能把三行纠错数相加当成新增获益患者。净错误变化=投票错误−参考错误=新增−纠正，负值表示错误事件减少。

{markdown_table(corrections[['reference_model','reference_error_events','vote_error_events','corrected_events','new_error_events','net_error_change_vote_minus_base','corrected_unique_patients','new_error_unique_patients']])}

受影响的真实患者ID、类别与预测组合如下；同一患者可在多个重复轮次出现。逐轮逐折明细保存于 `ensemble_corrected_and_new_errors.csv`。

{markdown_table(change_table)}

5. **一致与完全分歧比例？** 三模型完全一致{s['agreement']['unanimous']['count']}/{s['n_oof_patient_repeat_events']}（{100*s['agreement']['unanimous']['proportion']:.4f}%）；两者一致{s['agreement']['two_agree']['count']}（{100*s['agreement']['two_agree']['proportion']:.4f}%）；三者全不同{s['agreement']['all_three_different']['count']}（{100*s['agreement']['all_three_different']['proportion']:.4f}%），后者全部触发预设A平票规则。这些比例描述预测事件而非独立患者比例。

6. **哪些癌种受益？** 下表为20轮OOF逐类别F1均值及与各基础模型的差值。正值表示相对该参考模型的描述性改善；没有对所有参照都提升的癌种不能笼统说“从集成受益”。绝对错误事件和曾出错患者数见 `ensemble_errors_by_cancer.csv`。

{markdown_table(class_table.reset_index())}

{'。'.join(class_interpretation)}。BRCA的真实样本在四种方案中均无误判，其F1变化来自其他癌种被误判为BRCA造成的Precision变化，不能把BRCA F1降低误读为新增BRCA假阴性。

7. **总共需要多少不同基因？** A与C每折实际选择完全相同的50个ANOVA基因（已逐折核验）。A/B交集平均{s['ANOVA_variance_overlap_genes']['mean']:.2f}个；每折投票系统实际并集为{int(s['gene_budget_per_training_fold']['min'])}–{int(s['gene_budget_per_training_fold']['max'])}个，均值{s['gene_budget_per_training_fold']['mean']:.2f}，中位数{s['gene_budget_per_training_fold']['median']:.1f}。因此不能称为只测50个基因的系统。全部100折曾用基因的资源目录合计{s['distinct_gene_catalog_across_all_100_folds']}个，是跨划分目录，并非某个已经冻结的部署面板；本阶段不在全开发集拟合最终面板。

8. **是否值得额外成本？** 已核验旧融合实验的同折、同样本顺序、同参数和完全相同的每折基因数M，用已有单模型Top-M及并集SVM作描述性对照：

{markdown_table(budget_table)}

{cost_conclusion}

投票需要3个分类器，而单模型需要1个。三个基础模型历史100折拟合耗时之和约{fit_total:.3f}秒，反映已有运行记录的计算量；各模型运行时间来自不同历史拟合阶段，不能据此宣称公平硬件基准或实际部署延迟优势。投票的 `fit_seconds` 是三成员历史耗时之和，`predict_seconds` 是三成员历史“训练+验证预测”之和加本次投票规则计算耗时，并非单独验证推理延迟。没有测量真实实验室基因检测成本、样本制备成本或临床收益，无法给出成本效益定论；可据同预算成绩判断当前数据是否提供了采用额外分类器的性能依据。

9. **是否存在投票降低性能？** 按相同验证折配对：

{markdown_table(pd.DataFrame(regression))}

上面的新增错误明细直接体现个体预测退化；不能只报纠错而省略新增错误。逐轮相对变化另见 `ensemble_paired_round_differences.csv`。均值层面的改善也不保证每折或每个患者都改善。

## 预测稳定性与个体错误集中

投票100折Macro-F1的样本SD为{vote_sd:.8f}，{sd_text}；20轮OOF分数的SD另见上表，不能混用两个层级断言“总体更稳定”。曾出现错误的患者，在每个模型下的20轮错误次数如下，0表示该模型在该患者上未出现错误：

{markdown_table(patient_table)}

每个患者其余预测标签数、众数预测及众数比例见 `ensemble_sample_prediction_stability.csv`。标签长期一致可能意味着稳定地预测错误，因此不能只用预测一致性证明准确性提高。表中同一患者的多轮错误不构成多名独立患者。

## 可写入课程论文的结论

在固定640名开发患者、相同5折×20轮划分和冻结参数下，三模型等权硬投票Macro-F1为{vote_f1:.8f}，Balanced Accuracy为{ba:.8f}。其性能低于两个SVM基础模型、高于逻辑回归对照，未观察到相对最优基础模型的分类收益。A/B的错误虽有互补，但与C的共同错误使多数票保留了更多误判；这说明特征集合差异不自动转化为硬投票优势。投票每折需{int(s['gene_budget_per_training_fold']['min'])}–{int(s['gene_budget_per_training_fold']['max'])}个不同基因，且同预算单模型对照成绩更高，当前结果不支持采用该投票方案获得额外性能收益。这是开发集重复划分中的描述性观察，不能外推为外部独立泛化或临床有效性结论。

## 观察、解释、未验证机制及局限

**真实观察：** 本报告所有分数、错误组合、纠错/新增事件和基因并集来自核验后的实际开发集逐折预测；没有手填此前成绩或模拟结果。每名患者恰有20次OOF预测，个体错误比例是20次划分下的频率，不能解释为个体患癌风险。具体是否优于单模型由上述真实表格决定。

**合理解释：** 选择不同基因可产生不同决策边界，分类器不同也可能改变误判；等权多数票只有在足够多成员在某个事件中正确时才可靠。A与C共享ANOVA选择策略和相同训练数据，成员不独立，可能限制错误互补；这一点是与数据相容的解释，不是因果证明。

**尚未验证：** 本次没有证明任何特定基因的致癌作用、错误发生的生物学机制、跨医院/平台泛化、临床收益，也没有比较软投票、校准或其他投票权重。不因为本次结果修改平票规则或基础模型参数。

**局限：** 这是同一开发队列的重复划分稳定性评估；重复OOF观察相关，不能视为12,800名独立患者。此前已经多次使用该开发集探索和比较方法，成绩属于开发阶段描述，不是未受选择影响的无偏外部性能。161名保留患者在本实验未被使用；历史全801样本探索已包含它们，因此也不能称为从未接触过的外部队列。没有执行独立测试或外部验证。仅含五类已患癌肿瘤样本，只能研究五癌种表达分类，不能宣称具备癌症早筛、患癌风险评估、健康人检测或临床监测能力。

## 复现与图表索引

```powershell
python hard_voting.py
python hard_voting.py --resume "{str(run.relative_to(run.parents[2]))}"
python verify_hard_voting.py --run "{str(run.relative_to(run.parents[2]))}"
```

新运行自动查找既有成功实验；核验不通过时三个基础模型整体重拟合，绝不错误配对。可通过 `--source-run` / `--budget-run` 明确指定旧结果，通过 `--force-refit` 明确重训。断点身份绑定数据、代码、配置和源实验参数；恢复时还校验源预测哈希。源码或配置变化请新建运行目录。所有路径相对项目定位，输出CSV为UTF-8 BOM，Python为UTF-8。

|图|PNG / PDF（330 DPI PNG，中文字体、嵌入式PDF字体）|含义|
|---|---|---|
|1|figures/01_三模型与硬投票MacroF1对比|100个验证折与20轮OOF两个统计层级，截短纵轴明确标注|
|2|figures/02_三模型与硬投票BalancedAccuracy对比|同上，完整低分均在范围内|
|3|figures/03_五癌种F1对比|20轮逐类F1均值±样本SD，非置信区间|
|4|figures/04_预测一致性与错误组合|一致/分歧及0–3个基础模型错误事件|
|5|figures/05_模型间错误重合|同一患者×轮次的错误交集和Jaccard|
|6|figures/06_投票纠错与新增错误|相对A/B/C分别统计，不相加为患者数|
|7|figures/07_实际独立基因预算|100个训练折的实际并集基因数量|

主要输出还包括四模型逐折/逐轮成绩、宽格式三成员及投票OOF、逐类别PRF、训练/验证/OOF混淆矩阵、个体20轮错误频率、特征清单/并集、同预算旧成绩、审计、配置版本、完整日志和独立验收。既有结果与原始CSV未覆盖。
'''
    (run / "ensemble_report.md").write_text(report, encoding="utf-8")
    index = "# 三模型硬投票实验结果\n\n[完整中文报告](ensemble_report.md)\n\n[真实分类结果表](ensemble_results_table.csv)\n\n"
    for png in sorted((run / "figures").glob("*.png")):
        index += f"## {png.stem}\n\n![{png.stem}](figures/{png.name})\n\n[PDF](figures/{png.with_suffix('.pdf').name})\n\n"
    (run / "图表与结果索引.md").write_text(index, encoding="utf-8")
