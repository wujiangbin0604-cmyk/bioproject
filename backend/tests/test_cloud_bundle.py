"""上传包完整性测试不涉及训练、真实样本预测或测试集评分。"""
import json

import pytest

from cloud_deployment.verify import file_sha, verify_content


def test_bundle_detects_changed_bytes(tmp_path):
    model = tmp_path / "model.joblib"
    model.write_bytes(b"test fixture only")
    metadata = {"training_enabled": False, "raw_expression_data_included": False,
                "files": {"model.joblib": file_sha(model)}}
    (tmp_path / "bundle_manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    verify_content(tmp_path)
    model.write_bytes(b"modified fixture")
    with pytest.raises(ValueError, match="摘要不同"):
        verify_content(tmp_path)


@pytest.mark.parametrize("unsafe", ["../private", "/etc/passwd", "C:/secret", "folder\\secret"])
def test_bundle_rejects_outside_paths(tmp_path, unsafe):
    metadata = {"training_enabled": False, "raw_expression_data_included": False, "files": {unsafe: "0"*64}}
    (tmp_path / "bundle_manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="不安全路径"):
        verify_content(tmp_path)
