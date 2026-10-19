# -*- coding: utf-8 -*-
"""对真实第一阶段产出做独立验收；不重新训练模型，不执行后续实验。"""
from __future__ import annotations

from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.model_selection import StratifiedKFold, train_test_split

from baseline import build_baseline
from config import CLASS_ORDER, PROJECT_DIR, ExperimentConfig
from cross_validation import frozen_pipeline_record, make_cv
from data_loader import load_final_test, load_raw_data, write_json
from evaluation import compute_metrics, evaluate_final_test
from feature_selection import build_anova_search


def main() -> None:
    cfg = ExperimentConfig()
    latest = json.loads((cfg.output_dir / "latest_stage1.json").read_text(encoding="utf-8"))
    output = cfg.output_dir / latest["run_directory"]
    recorded_cfg = json.loads((output / "config.json").read_text(encoding="utf-8"))
    cfg = replace(cfg, data_dir=Path(recorded_cfg["data_dir"]),
                  raw_archive=Path(recorded_cfg["raw_archive"]))
    raw = load_raw_data(cfg)
    checks = []

    def check(name: str, condition) -> None:
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    manifest = json.loads((output / "split_manifest.json").read_text(encoding="utf-8"))
    saved = json.loads(cfg.split_manifest_path.read_text(encoding="utf-8"))
    check("数据维度和原始基因名称保留", raw.X.shape == (801, 20531) and
          list(raw.X.columns) == [f"gene_{i}" for i in range(20531)])
    check("缺失无穷重复和非数值均通过真实检查", all(raw.quality[key] == 0 for key in
          ("missing_values", "infinite_values", "duplicate_expression_profiles", "nonnumeric_columns")))
    dev, test = train_test_split(raw.X.index.to_numpy(), test_size=0.2,
                                 stratify=raw.y.to_numpy(), random_state=42)
    check("固定划分与指定train_test_split一致", list(dev) == manifest["development_ids"] and
          list(test) == manifest["reserved_test_ids"] and saved == manifest)
    check("开发640测试161且无交集", len(dev) == 640 and len(test) == 161 and not set(dev) & set(test))
    check("原始数据指纹匹配", raw.fingerprint == manifest["dataset_fingerprint_sha256"])
    folds = json.loads((output / "cv_fold_indices.json").read_text(encoding="utf-8"))["folds"]
    details = pd.read_csv(output / "cv_fold_details.csv")
    pred = pd.read_csv(output / "development_oof_predictions.csv")
    audit = pd.read_csv(output / "fold_fit_audit.csv")
    check("仅执行5次标准CV", len(details) == len(folds) == 5 and set(details.cv_mode) == {"standard"})
    check("所有模型输入特征均为20531", (details.n_features_input == 20531).all() and
          (details.n_features_model == 20531).all())
    check("C=1为固定基线", (details.C == 1).all() and set(details.selection_method) == {"none"})
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    for i, (train_idx, valid_idx) in enumerate(skf.split(raw.X.loc[dev], raw.y.loc[dev]), start=1):
        fold = folds[i - 1]
        check(f"第{i}折索引与指定分层CV一致", fold["train_sample_ids"] == dev[train_idx].tolist() and
              fold["validation_sample_ids"] == dev[valid_idx].tolist())
        check(f"第{i}折仅含开发样本且无泄漏交集", len(train_idx) == 512 and len(valid_idx) == 128 and
              not set(fold["train_sample_ids"]) & set(fold["validation_sample_ids"]) and
              not (set(fold["train_sample_ids"]) | set(fold["validation_sample_ids"])) & set(test))
        fold_predictions = pred.loc[pred.evaluation_id == i]
        check(f"第{i}折真实标签与验证ID一致", list(fold_predictions.sample_id) == fold["validation_sample_ids"] and
              list(fold_predictions.y_true) == list(raw.y.loc[fold_predictions.sample_id]))
        metrics = compute_metrics(fold_predictions.y_true, fold_predictions.y_pred)
        row = details.loc[details.evaluation_id == i].iloc[0]
        check(f"第{i}折验证分数可由OOF预测复算", all(np.isclose(row[f"validation_{key}"], value)
              for key, value in metrics.items()))
    check("640个开发样本均仅有一次折外预测", len(pred) == 640 and not pred.sample_id.duplicated().any() and
          set(pred.sample_id) == set(dev) and not set(pred.sample_id) & set(test))
    check("折内标准化样本数与均值方差核查通过", audit.scaler_fit_audit_passed.all() and
          (audit.scaler_training_samples == 512).all() and (audit.scaler_features == 20531).all() and
          (audit.train_validation_overlap == 0).all() and (audit.reserved_test_overlap == 0).all())
    summary = pd.read_csv(output / "cv_summary.csv").iloc[0]
    for metric in ("macro_f1", "balanced_accuracy"):
        values = details[f"validation_{metric}"]
        check(f"{metric}均值标准差及差距准确", np.isclose(summary[f"validation_{metric}_mean"], values.mean()) and
              np.isclose(summary[f"validation_{metric}_std"], values.std(ddof=1)) and
              np.allclose(details[f"gap_{metric}"], details[f"train_{metric}"] - values))
    status = json.loads((output / "stage_status.json").read_text(encoding="utf-8"))
    check("后续五个阶段与测试评分未运行", status["stage_1"] == "complete" and
          all(status[f"stage_{i}"] == "not_run" for i in range(2, 7)) and
          status["test_evaluation_performed"] is False and status["hyperparameter_search_performed"] is False)
    for guard in (load_final_test, evaluate_final_test):
        blocked = False
        try:
            guard()
        except NotImplementedError:
            blocked = True
        check(f"{guard.__name__}最终测试入口受限", blocked)
    check("重复CV支持100次评估但没有执行", make_cv(replace(cfg, cv_mode="repeated")).get_n_splits() == 100)
    for classifier in ("linear_svm", "logistic_regression"):
        search = build_anova_search(cfg, classifier)
        check(f"{classifier}后续网格和Pipeline工厂未fit", not hasattr(search, "best_estimator_") and
              search.param_grid["select__k"] == list(cfg.k_values) and
              search.param_grid["model__C"] == list(cfg.c_grid) and
              [name for name, _ in search.estimator.steps] == ["select", "scale", "model"])
    # 只比较配置记录，不运行任何重复CV或稳定性拟合。
    original = build_baseline(cfg)
    changed = build_baseline(cfg).set_params(model__class_weight="balanced")
    check("冻结配置区分全部模型设置", frozen_pipeline_record(original, "baseline", "none", "all") !=
          frozen_pipeline_record(changed, "baseline", "none", "all"))
    for path in sorted((output / "figures").glob("*.png")):
        with Image.open(path) as image:
            image.load()
            check(path.name + "可读且至少300DPI", min(image.info.get("dpi", (0, 0))) >= 300)
    check("两个PNG和两个PDF均存在", len(list((output / "figures").glob("*.png"))) == 2 and
          len(list((output / "figures").glob("*.pdf"))) == 2)
    source_hashes = {}
    for path in sorted(PROJECT_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    check("全部源文件为UTF8且语法有效", True)
    write_json(output / "verification.json", {"status": "passed", "checks": checks,
               "n_checks": len(checks), "test_evaluation_performed": False,
               "source_sha256": source_hashes})
    packages = ("numpy", "pandas", "scikit-learn", "matplotlib", "scipy", "threadpoolctl", "joblib", "pillow")
    (PROJECT_DIR / "requirements.lock.txt").write_text(
        "# 本次真实运行的依赖版本；Python版本见environment.json\n" +
        "\n".join(f"{package}=={version(package)}" for package in packages) + "\n", encoding="utf-8")
    print(f"验收通过：{len(checks)}项；未重新训练模型，未执行保留测试。")
    print(f"结果目录：{output}")


if __name__ == "__main__":
    main()
