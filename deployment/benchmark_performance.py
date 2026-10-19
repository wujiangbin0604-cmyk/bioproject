# -*- coding: utf-8 -*-
"""重复测量单样本CSV解析、校验、模型加载、模型预测及CLI端到端耗时。"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Callable

import joblib
import numpy as np
import pandas as pd
import sklearn

try:
    from .input_validator import validate_single_sample
    from .model_loader import DEFAULT_MODEL_PATH, load_deployment_model
except ImportError:  # `python deployment/benchmark_performance.py`
    from input_validator import validate_single_sample
    from model_loader import DEFAULT_MODEL_PATH, load_deployment_model

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = PACKAGE_DIR / "examples" / "sample_input.csv"
REPORT_DIR = PACKAGE_DIR / "reports"
PREDICT_SCRIPT = PACKAGE_DIR / "predict.py"


def _measure(name: str, repeats: int, function: Callable[[], object]) -> list[dict[str, object]]:
    rows = []
    for run in range(1, repeats + 1):
        start = time.perf_counter()
        function()
        rows.append({"metric": name, "repeat": run, "seconds": time.perf_counter() - start})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--repeats", type=int, default=3,
                        help="每项至少重复3次；默认3次，报告中位数")
    parser.add_argument("--label", choices=("before", "after"), required=True,
                        help="将结果保存为优化前(before)或优化后(after)基准文件")
    args = parser.parse_args(argv)
    if args.repeats < 3:
        parser.error("repeats必须至少为3")
    if not args.input.is_file():
        parser.error(f"找不到输入CSV：{args.input}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    loaded = load_deployment_model(args.model)
    rows: list[dict[str, object]] = []

    rows += _measure("csv_read", args.repeats,
                     lambda: pd.read_csv(args.input, encoding="utf-8-sig"))
    validated_holder: list[object] = []

    def validate() -> None:
        validated_holder[:] = [validate_single_sample(args.input, loaded.feature_names)]

    rows += _measure("input_validation", args.repeats, validate)
    validated = validated_holder[0]
    rows += _measure("model_load", args.repeats,
                     lambda: load_deployment_model(args.model))
    rows += _measure("model_prediction", args.repeats,
                     lambda: loaded.pipeline.predict(validated.features))

    with tempfile.TemporaryDirectory(prefix="benchmark_", dir=REPORT_DIR) as temp_dir:
        output_dir = Path(temp_dir)

        def run_cli(index: int) -> Callable[[], object]:
            def invoke() -> subprocess.CompletedProcess[str]:
                output = output_dir / f"prediction_{index}.json"
                completed = subprocess.run(
                    [sys.executable, str(PREDICT_SCRIPT), "--input", str(args.input),
                     "--model", str(args.model), "--output", str(output)],
                    cwd=PACKAGE_DIR.parent, text=True, encoding="utf-8", errors="replace",
                    capture_output=True, check=False, timeout=300)
                if completed.returncode != 0:
                    raise RuntimeError(f"CLI基准失败：{completed.stderr}")
                result = json.loads(output.read_text(encoding="utf-8"))
                if result.get("predicted_class") not in loaded.metadata["classifier_class_order"]:
                    raise RuntimeError("CLI输出类别不在冻结类别集合中")
                return completed
            return invoke

        for repeat in range(1, args.repeats + 1):
            rows += _measure("cli_end_to_end", 1, run_cli(repeat))
            rows[-1]["repeat"] = repeat

    measurements = pd.DataFrame(rows)
    summary = (measurements.groupby("metric", sort=False)["seconds"]
               .agg(median_seconds="median", mean_seconds="mean", min_seconds="min",
                    max_seconds="max", measurements="count").reset_index())
    summary_path = REPORT_DIR / f"输入校验性能_优化{args.label}.csv"
    raw_path = REPORT_DIR / f"输入校验性能_优化{args.label}_重复测量.csv"
    json_path = REPORT_DIR / f"输入校验性能_优化{args.label}.json"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    measurements.to_csv(raw_path, index=False, encoding="utf-8-sig")
    environment = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(), "numpy": np.__version__,
        "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__, "platform": platform.platform(),
        "input_filename": args.input.name, "input_bytes": args.input.stat().st_size,
        "input_feature_count": len(loaded.feature_names), "repeat_count": args.repeats,
        "model_sha256": loaded.metadata["model_artifact_sha256"],
        "measurements": {row.metric: {"median_seconds": float(row.median_seconds),
                                       "mean_seconds": float(row.mean_seconds),
                                       "min_seconds": float(row.min_seconds),
                                       "max_seconds": float(row.max_seconds),
                                       "count": int(row.measurements)}
                         for row in summary.itertuples(index=False)},
    }
    json_path.write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"结果：{summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
