# -*- coding: utf-8 -*-
"""研究项目内验证：使用固定开发集的一条记录检查部署API/CLI。"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ExperimentConfig
from data_loader import load_existing_development_data
from deployment.model_loader import load_deployment_model

DEPLOYMENT = ROOT / "deployment"
LOCAL_DIR = DEPLOYMENT / "examples" / "local_validation"
REPORT_DIR = DEPLOYMENT / "reports"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, check=False, timeout=300)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, object] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "research-project development-only integration check",
        "reserved_test_expression_or_label_used": False,
        "reserved_test_prediction_or_score_computed": False,
        "model_training_performed": False,
        "test_labels_read": False,
        "status": "failed",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="research_validation_", dir=REPORT_DIR) as temp:
            data = load_existing_development_data(ExperimentConfig(), Path(temp), strict_rows_only=True)
            if data.X.shape != (640, 20531):
                raise RuntimeError(f"固定开发集维度错误：{data.X.shape}")
            sample = data.X.iloc[[0]].copy()
            sample.insert(0, "sample_id", str(sample.index[0]))
            input_path = LOCAL_DIR / "dev_sample_input.csv"
            sample.to_csv(input_path, index=False, encoding="utf-8-sig")
            expected = str(load_deployment_model().pipeline.predict(data.X.iloc[[0]])[0])

        output_path = LOCAL_DIR / "dev_sample_prediction.json"
        completed = _run([sys.executable, str(DEPLOYMENT / "predict.py"), "--input", str(input_path),
                          "--output", str(output_path)], ROOT)
        if completed.returncode != 0:
            raise RuntimeError(f"开发集格式样本CLI推理失败：{completed.stderr}")
        prediction = json.loads(output_path.read_text(encoding="utf-8"))
        if prediction.get("predicted_class") != expected:
            raise RuntimeError("CLI与冻结Pipeline预测不一致")

        tests = _run([sys.executable, "-m", "unittest", "discover", "-s",
                      str(DEPLOYMENT / "tests"), "-p", "test_*.py", "-v"], ROOT)
        test_log = tests.stdout + tests.stderr
        (REPORT_DIR / "pytest_run.log").write_text(test_log, encoding="utf-8")
        if tests.returncode != 0:
            raise RuntimeError(f"pytest运行失败：\n{test_log}")
        result.update({
            "status": "passed", "development_samples": 640, "raw_gene_count": 20531,
            "sample_id_written_to_ignored_local_validation": True,
            "sample_label_saved": False, "api_cli_pipeline_prediction_match": True,
            "pytest_log": "pytest_run.log", "pytest_output": test_log.strip(),
            "model_sha256": load_deployment_model().metadata["model_artifact_sha256"],
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    output = REPORT_DIR / "full_project_validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "passed":
        print(result.get("traceback", result.get("error", "validation failed")), file=sys.stderr)
        return 1
    print("full-project development validation passed")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
