# -*- coding: utf-8 -*-
"""单样本预测部署的自动化输入、工件及推理一致性测试。"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from input_validator import InputValidationError, validate_single_sample
from model_loader import (
    MODEL_VERSION, ModelArtifactError, load_deployment_model, metadata_path_for,
)
import model_loader
from predict import PredictionError, predict_single_sample

DEPLOYMENT = PACKAGE_ROOT
EXAMPLE = PACKAGE_ROOT / "examples" / "sample_input.csv"
DEV_EXAMPLE = PACKAGE_ROOT / "examples" / "local_validation" / "dev_sample_input.csv"
PREDICT_SCRIPT = PACKAGE_ROOT / "predict.py"
TEST_TEMP_ROOT = PACKAGE_ROOT / "reports" / "test_tmp"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Windows沙箱中的系统TEMP目录可能不可写；测试临时工件放在项目可写目录。
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.loaded = load_deployment_model()
        source = DEV_EXAMPLE if DEV_EXAMPLE.is_file() else EXAMPLE
        cls.sample_source = source
        cls.sample = pd.read_csv(source, encoding="utf-8-sig")
        cls.feature_names = cls.loaded.feature_names

    def test_a_model_loads_with_all_fitted_pipeline_components(self) -> None:
        pipeline = self.loaded.pipeline
        self.assertEqual(list(pipeline.named_steps), ["select", "scale", "model"])
        self.assertEqual(pipeline.named_steps["select"].k, 50)
        self.assertEqual(pipeline.named_steps["select"].n_features_in_, 20531)
        self.assertEqual(pipeline.named_steps["scale"].n_features_in_, 50)
        self.assertEqual(pipeline.named_steps["scale"].n_samples_seen_, 640)
        self.assertEqual(pipeline.named_steps["model"].C, 1.0)
        self.assertEqual(pipeline.named_steps["model"].dual, "auto")
        self.assertTrue(hasattr(pipeline.named_steps["model"], "coef_"))
        self.assertEqual(len(self.loaded.selected_gene_names), 50)

    def test_b_real_development_record_is_accepted_without_label(self) -> None:
        if not DEV_EXAMPLE.is_file():
            self.skipTest("本地开发集样本仅在有原始数据的工作区生成")
        result = predict_single_sample(DEV_EXAMPLE)
        self.assertIn(result["predicted_class"], self.loaded.metadata["classifier_class_order"])
        self.assertEqual(result["input_feature_count"], 20531)
        self.assertEqual(result["selected_feature_count"], 50)
        self.assertEqual(result["inference_status"], "success")

    def test_c_api_matches_direct_saved_pipeline_prediction(self) -> None:
        valid = validate_single_sample(self.sample, self.feature_names)
        expected = str(self.loaded.pipeline.predict(valid.features)[0])
        result = predict_single_sample(self.sample)
        self.assertEqual(result["predicted_class"], expected)
        self.assertIn(result["predicted_class"], self.loaded.metadata["classifier_class_order"])
        self.assertFalse(result["probability_output"])

    def test_d_gene_columns_are_reordered_by_name(self) -> None:
        genes = list(self.feature_names)
        permuted = np.random.default_rng(42).permutation(genes).tolist()
        columns = (["sample_id"] if "sample_id" in self.sample.columns else []) + permuted
        shuffled = self.sample.loc[:, columns]
        direct = predict_single_sample(self.sample)
        reordered = predict_single_sample(shuffled)
        self.assertEqual(reordered["predicted_class"], direct["predicted_class"])
        self.assertTrue(reordered["input_columns_reordered"])

    def test_e_missing_gene_is_rejected_with_gene_name(self) -> None:
        missing_gene = self.feature_names[-1]
        with self.assertRaisesRegex(InputValidationError, missing_gene):
            validate_single_sample(self.sample.drop(columns=[missing_gene]), self.feature_names)

    def test_f_duplicate_gene_header_in_csv_is_rejected(self) -> None:
        duplicate = self.sample.copy()
        duplicate.columns = ["gene_0" if str(name) == "gene_1" else name for name in duplicate.columns]
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            path = Path(folder) / "duplicate.csv"
            duplicate.to_csv(path, index=False, encoding="utf-8-sig")
            with self.assertRaisesRegex(PredictionError, "重复列名"):
                predict_single_sample(path)

    def test_g_nan_is_rejected(self) -> None:
        bad = self.sample.copy()
        bad.loc[0, self.feature_names[0]] = np.nan
        with self.assertRaisesRegex(InputValidationError, "NaN"):
            validate_single_sample(bad, self.feature_names)

    def test_h_positive_infinity_is_rejected(self) -> None:
        bad = self.sample.copy()
        bad.loc[0, self.feature_names[0]] = np.inf
        with self.assertRaisesRegex(InputValidationError, "无穷"):
            validate_single_sample(bad, self.feature_names)

    def test_i_negative_infinity_is_rejected(self) -> None:
        bad = self.sample.copy()
        bad.loc[0, self.feature_names[0]] = -np.inf
        with self.assertRaisesRegex(InputValidationError, "无穷"):
            validate_single_sample(bad, self.feature_names)

    def test_j_non_numeric_expression_is_rejected(self) -> None:
        bad = self.sample.copy()
        bad[self.feature_names[0]] = "not-a-number"
        with self.assertRaisesRegex(InputValidationError, "非数值"):
            validate_single_sample(bad, self.feature_names)

    def test_k_unknown_extra_gene_is_rejected(self) -> None:
        bad = self.sample.copy()
        bad["gene_unknown"] = 1.0
        with self.assertRaisesRegex(InputValidationError, "gene_unknown"):
            validate_single_sample(bad, self.feature_names)

    def test_l_sample_id_is_allowed_and_not_passed_as_feature(self) -> None:
        result = predict_single_sample(self.sample)
        self.assertEqual(result["sample_id"], str(self.sample.loc[0, "sample_id"]))
        self.assertEqual(result["input_feature_count"], 20531)
        self.assertNotIn("sample_id", self.loaded.feature_names)

    def test_m_empty_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            path = Path(folder) / "empty.csv"
            path.write_bytes(b"")
            with self.assertRaisesRegex(PredictionError, "空文件"):
                predict_single_sample(path)

    def test_m1_invalid_utf8_is_rejected_clearly(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            path = Path(folder) / "invalid_encoding.csv"
            path.write_bytes(b"\xff\xfe\x00\x00")
            with self.assertRaisesRegex(PredictionError, "UTF-8"):
                predict_single_sample(path)

    def test_m2_unsupported_extension_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            path = Path(folder) / "input.tsv"
            path.write_text("gene_0\tgene_1\n1\t2\n", encoding="utf-8")
            with self.assertRaisesRegex(PredictionError, "不支持的文件格式"):
                predict_single_sample(path)

    def test_m3_gene_spelling_error_identifies_missing_name(self) -> None:
        bad = self.sample.rename(columns={self.feature_names[0]: f"{self.feature_names[0]} "})
        with self.assertRaisesRegex(InputValidationError, "gene_0"):
            validate_single_sample(bad, self.feature_names)

    def test_m4_modified_metadata_hash_is_rejected(self) -> None:
        original = self.loaded.model_path
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            destination = Path(folder) / "metadata-tampered.joblib"
            shutil.copy2(original, destination)
            sidecar = metadata_path_for(destination)
            shutil.copy2(metadata_path_for(original), sidecar)
            sidecar.write_text(sidecar.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ModelArtifactError, "元数据SHA-256"):
                load_deployment_model(destination)

    def test_n_exactly_one_sample_is_required(self) -> None:
        multiple = pd.concat([self.sample, self.sample], ignore_index=True)
        with self.assertRaisesRegex(InputValidationError, "恰好1行"):
            validate_single_sample(multiple, self.feature_names)

    def test_o_missing_model_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ModelArtifactError, "找不到模型文件"):
            load_deployment_model(DEPLOYMENT / "models" / "missing.joblib")

    def test_p_modified_model_hash_is_rejected_before_deserialization(self) -> None:
        original = self.loaded.model_path
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            destination = Path(folder) / "tampered.joblib"
            shutil.copy2(original, destination)
            shutil.copy2(metadata_path_for(original), metadata_path_for(destination))
            with destination.open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaisesRegex(ModelArtifactError, "SHA-256"):
                load_deployment_model(destination)

    def test_q_corrupted_model_is_rejected_safely(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            destination = Path(folder) / "corrupt.joblib"
            destination.write_bytes(b"not a valid trusted model serialization")
            metadata = copy.deepcopy(self.loaded.metadata)
            metadata["model_artifact_file"] = destination.name
            metadata["model_artifact_sha256"] = digest(destination)
            sidecar = metadata_path_for(destination)
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            with patch.object(model_loader, "TRUSTED_MODEL_SHA256", digest(destination)), \
                 patch.object(model_loader, "TRUSTED_METADATA_SHA256", digest(sidecar)):
                with self.assertRaisesRegex(ModelArtifactError, "无法反序列化"):
                    load_deployment_model(destination)

    def test_r_model_version_mismatch_is_rejected(self) -> None:
        original = self.loaded.model_path
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            destination = Path(folder) / "versioned.joblib"
            shutil.copy2(original, destination)
            metadata = copy.deepcopy(self.loaded.metadata)
            metadata["model_version"] = "M1-unknown-version"
            sidecar = metadata_path_for(destination)
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            with patch.object(model_loader, "TRUSTED_METADATA_SHA256", digest(sidecar)):
                with self.assertRaisesRegex(ModelArtifactError, "模型版本不匹配"):
                    load_deployment_model(destination)

    def test_s_scikit_learn_version_mismatch_is_rejected(self) -> None:
        original = self.loaded.model_path
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            destination = Path(folder) / "dependency-version.joblib"
            shutil.copy2(original, destination)
            metadata = copy.deepcopy(self.loaded.metadata)
            metadata["environment"]["scikit-learn"] = "0.0-test-mismatch"
            sidecar = metadata_path_for(destination)
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            with patch.object(model_loader, "TRUSTED_METADATA_SHA256", digest(sidecar)):
                with self.assertRaisesRegex(ModelArtifactError, "版本不匹配"):
                    load_deployment_model(destination)

    def test_t_repeated_predictions_are_deterministic_and_do_not_mutate_model(self) -> None:
        pipeline = self.loaded.pipeline
        selector = pipeline.named_steps["select"]
        scaler = pipeline.named_steps["scale"]
        classifier = pipeline.named_steps["model"]
        before_params = pipeline.get_params(deep=True)
        before_arrays = [selector.scores_.copy(), selector.get_support().copy(),
                         scaler.mean_.copy(), scaler.scale_.copy(), classifier.coef_.copy(),
                         classifier.intercept_.copy(), classifier.classes_.copy()]
        results = [predict_single_sample(self.sample)["predicted_class"] for _ in range(3)]
        self.assertEqual(results, [results[0]] * 3)
        self.assertEqual(pipeline.get_params(deep=True), before_params)
        after_arrays = [selector.scores_, selector.get_support(), scaler.mean_, scaler.scale_,
                        classifier.coef_, classifier.intercept_, classifier.classes_]
        for before, after in zip(before_arrays, after_arrays):
            np.testing.assert_array_equal(before, after)

    def test_u_cli_writes_json_and_shows_clear_prediction(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            output = Path(folder) / "prediction.json"
            completed = subprocess.run(
                [sys.executable, str(PREDICT_SCRIPT), "--input", str(EXAMPLE),
                 "--output", str(output), "--verbose"], cwd=PACKAGE_ROOT,
                text=True, capture_output=True, check=False, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("预测类别：", completed.stdout)
            self.assertIn("推理状态：推理完成", completed.stdout)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["sample_id"], "synthetic_format_example")
            self.assertEqual(result["selected_feature_count"], 50)
            self.assertIn(result["predicted_class"], self.loaded.metadata["classifier_class_order"])

    def test_v_python_runtime_version_mismatch_is_rejected(self) -> None:
        original = self.loaded.model_path
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            destination = Path(folder) / "python-version.joblib"
            shutil.copy2(original, destination)
            metadata = copy.deepcopy(self.loaded.metadata)
            metadata["environment"]["python"] = "0.0-test-mismatch"
            sidecar = metadata_path_for(destination)
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            with patch.object(model_loader, "TRUSTED_METADATA_SHA256", digest(sidecar)):
                with self.assertRaisesRegex(ModelArtifactError, "python:要求"):
                    load_deployment_model(destination)


if __name__ == "__main__":
    unittest.main(verbosity=2)
