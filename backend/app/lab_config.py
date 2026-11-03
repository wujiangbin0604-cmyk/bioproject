"""实验室合法配置及持久化约定；不接受浏览器提交代码、路径或测试集。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator

PROJECT = Path(__file__).resolve().parents[2]
TASK_ROOT = PROJECT / "results" / "lab_experiments"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
DEVELOPMENT_SHA = "23413d45a8bad213a2190d0bde01d5030ebcc8370c34397f88277c4b4fc69da5"


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classifier: Literal["linear_svm", "logistic_regression"] = "linear_svm"
    selection: Literal["all", "anova", "variance"] = "anova"
    k: Literal[20, 50, 100, 300, 500, 1000] = 50
    c: Literal[0.1, 1.0, 10.0] = 1.0
    cv_mode: Literal["standard", "repeated"] = "standard"

    @model_validator(mode="after")
    def normalize(self):
        # 全特征模式忽略K；固定为规范值，防止同一实验产生多个身份。
        if self.selection == "all":
            self.k = 50
        return self


def limits():
    return {"max_concurrent_tasks": 1, "numeric_threads": 1,
            "timeout_seconds": max(60, min(1800, int(os.getenv("GENESCOPE_LAB_TIMEOUT", "900")))),
            "memory_limit_mb": max(512, min(4096, int(os.getenv("GENESCOPE_LAB_MEMORY_MB", "2048")))),
            "minimum_available_memory_mb": max(512, min(4096, int(os.getenv("GENESCOPE_LAB_MIN_AVAILABLE_MB", "1024")))),
            "max_saved_tasks": 100, "n_splits": 5, "n_repeats": 20, "random_state": 42}


def task_root(project_root: Path = PROJECT) -> Path:
    """云端仅将现场结果写入独立持久化卷；隔离测试目录不采用生产环境路径。"""
    override = os.getenv("GENESCOPE_LAB_TASK_ROOT")
    return Path(override).resolve() if override and Path(project_root).resolve() == PROJECT else Path(project_root) / "results/lab_experiments"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    # Windows readers/antivirus can briefly hold the destination without delete sharing.
    # Retry the atomic replace; never fall back to truncating a state file being read.
    for attempt in range(12):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 11:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(min(.01 * (attempt + 1), .1))
