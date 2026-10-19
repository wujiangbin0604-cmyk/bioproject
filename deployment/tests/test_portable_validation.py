# -*- coding: utf-8 -*-
"""回归测试：便携验证必须在只有deployment目录的解压副本中运行。"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

DEPLOYMENT = Path(__file__).resolve().parents[1]
TEMP_ROOT = DEPLOYMENT / "reports" / "test_tmp"


class PortableValidationTests(unittest.TestCase):
    def test_validator_runs_in_extracted_deployment_without_research_source(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="portable_validator_", dir=TEMP_ROOT) as temp:
            workspace = Path(temp)
            cloned = workspace / "deployment"
            shutil.copytree(
                DEPLOYMENT, cloned,
                ignore=shutil.ignore_patterns("__pycache__", "local_validation", "test_tmp"),
            )
            completed = subprocess.run(
                [sys.executable, str(cloned / "validate_deployment.py")],
                cwd=workspace, text=True, encoding="utf-8", errors="replace",
                capture_output=True, check=False, timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("portable validation passed", completed.stdout.lower())
            self.assertTrue((cloned / "reports" / "portable_validation.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
