"""真实本机验收：一个已确认开发样本的六模型推理、一次5折CV与取消。

必须显式运行；不属于常规pytest，不用模拟数据生成实验成绩。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import time
import zipfile

import pandas as pd
from sklearn.metrics import f1_score, balanced_accuracy_score
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("GENESCOPE_SMOKE_BASE", "http://127.0.0.1:5173")
ARTIFACTS = ROOT / "backend" / "tests" / ".smoke"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def hashes():
    files = [*ROOT.glob("results/latest_*.json"), *ROOT.glob("results/final_holdout_evaluation/models/*.joblib"),
             ROOT / "data/split_manifest.json", ROOT / "results/final_holdout_evaluation/final_configuration.json",
             ROOT / "results/final_holdout_evaluation/final_evaluation_audit.json", *ROOT.glob("deployment/models/*")]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}


def main():
    ARTIFACTS.mkdir(exist_ok=True, parents=True)
    sample = ROOT / "deployment/examples/local_validation/dev_sample_input.csv"
    with sample.open(encoding="utf-8-sig", newline="") as stream:
        record = next(csv.DictReader(stream))
    manifest = json.loads((ROOT / "data/split_manifest.json").read_text(encoding="utf-8"))
    assert record["sample_id"] in manifest["development_ids"]
    assert record["sample_id"] not in manifest["reserved_test_ids"]
    before = hashes()
    errors = []
    output = {"source": "real_local_browser_acceptance", "base_url": BASE, "sample_scope": "confirmed_fixed_development_id"}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EDGE, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/lab", wait_until="networkidle", timeout=60000)
        page.get_by_role("heading", name="交互式模型实验室", exact=True).wait_for()
        registry = page.request.get(BASE + "/api/v1/lab/models").json()["models"]
        assert len(registry) == 6 and all(model["available"] for model in registry), registry
        for model in registry:
            page.get_by_label("选择" + model["model_id"], exact=True).check()
        page.get_by_label("实验室单样本CSV").set_input_files(sample)
        with page.expect_response(lambda response: response.url.endswith("/lab/predict")) as response_info:
            page.get_by_role("button", name="运行所选模型", exact=True).click()
        inference = response_info.value.json()
        assert len(inference["results"]) == 6 and all(row["status"] == "success" for row in inference["results"]), inference
        page.get_by_text("现场冻结模型推理输出", exact=True).wait_for()
        page.screenshot(path=str(ARTIFACTS / "lab_inference.png"), full_page=True)
        output["inference"] = inference
        page.locator(".lab-mode-switch button").nth(1).click()
        with page.expect_response(lambda response: response.url.endswith("/lab/tasks") and response.request.method == "POST") as created:
            page.get_by_role("button", name="提交真实交叉验证任务", exact=True).click()
        assert created.value.status == 202, created.value.text()
        task_id = created.value.json()["task_id"]
        page.evaluate("""id => {
          window.labSnapshots = [];
          const events = new EventSource(`/api/v1/lab/tasks/${id}/events`);
          events.addEventListener('snapshot', event => {
            const state = JSON.parse(event.data);
            window.labSnapshots.push({status: state.status, completed_folds: state.completed_folds});
            if (['completed','failed','cancelled','interrupted'].includes(state.status)) events.close();
          });
        }""", task_id)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = page.request.get(BASE + f"/api/v1/lab/tasks/{task_id}").json()
            if state["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(.3)
        assert state["status"] == "completed" and state["completed_folds"] == 5, state
        page.get_by_text("现场开发集交叉验证完成，未评价保留集", exact=True).wait_for(timeout=15000)
        assert page.locator(".lab-page canvas").count() > 0
        snapshots = page.evaluate("window.labSnapshots")
        assert any(s["status"] in {"loading", "running", "queued"} for s in snapshots), snapshots
        output["standard_task"] = state
        output["sse_snapshots"] = snapshots
        page.screenshot(path=str(ARTIFACTS / "lab_training.png"), full_page=True)
        exported = page.request.get(BASE + f"/api/v1/lab/tasks/{task_id}/export")
        assert exported.status == 200
        with zipfile.ZipFile(io.BytesIO(exported.body())) as archive:
            folds = pd.read_csv(archive.open("fold_results.csv"))
            predictions = pd.read_csv(archive.open("oof_predictions.csv"))
            audit = pd.read_csv(archive.open("fit_audit.csv"))
            indices = json.loads(archive.read("cv_indices.json"))
            assert len(folds) == 5 and len(predictions) == 640 and predictions.sample_id.nunique() == 640
            for row in folds.to_dict("records"):
                subset = predictions[predictions.fold_id.eq(row["fold_id"])]
                assert abs(f1_score(subset.true_label, subset.predicted_class, average="macro")-row["validation_macro_f1"]) < 1e-12
                assert abs(balanced_accuracy_score(subset.true_label, subset.predicted_class)-row["validation_balanced_accuracy"]) < 1e-12
            assert audit.reserved_fit_or_predict_count.eq(0).all()
            assert audit.scaler_fit_samples.eq(512).all()
            assert audit.scaler_mean_matches_train.all() and audit.scaler_variance_matches_train.all()
            for fold in indices:
                train, valid = set(fold["train_ids"]), set(fold["validation_ids"])
                assert not train & valid and train | valid == set(manifest["development_ids"])
                assert not (train | valid) & set(manifest["reserved_test_ids"])
            assert "split_manifest.json" not in archive.namelist()
        output["export_independently_recomputed"] = True
        page.get_by_label("实验交叉验证", exact=True).select_option("repeated")
        with page.expect_response(lambda response: response.url.endswith("/lab/tasks") and response.request.method == "POST") as created:
            page.get_by_role("button", name="提交真实交叉验证任务", exact=True).click()
        second_id = created.value.json()["task_id"]
        conflict = page.request.post(BASE + "/api/v1/lab/tasks", data={"selection": "anova"})
        assert conflict.status == 409, conflict.text()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state2 = page.request.get(BASE + f"/api/v1/lab/tasks/{second_id}").json()
            if state2["completed_folds"] >= 1 or state2["status"] in {"failed", "completed"}:
                break
            time.sleep(.3)
        assert state2["status"] == "running", state2
        page.get_by_role("button", name="取消当前任务", exact=True).click()
        page.get_by_text("用户取消任务；已完成折的结果已保留", exact=True).wait_for(timeout=15000)
        output["cancelled_task"] = page.request.get(BASE + f"/api/v1/lab/tasks/{second_id}").json()
        assert output["cancelled_task"]["status"] == "cancelled"
        output["concurrent_submission_status"] = conflict.status
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(BASE + "/lab", wait_until="networkidle")
        mobile.get_by_role("heading", name="交互式模型实验室", exact=True).wait_for()
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        mobile.screenshot(path=str(ARTIFACTS / "lab_mobile.png"), full_page=True)
        browser.close()
    assert not errors, errors
    assert hashes() == before, "已有正式工件或指针被更改"
    output.update(browser_page_errors=errors, historical_artifacts_unchanged=True, test_set_evaluated=False)
    destination = ROOT / "reports/lab_validation.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "standard_task_id": task_id, "cancelled_task_id": second_id,
                      "fold_macro_f1": [f["validation_macro_f1"] for f in output["standard_task"]["folds"]],
                      "inference": inference["results"], "page_errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
