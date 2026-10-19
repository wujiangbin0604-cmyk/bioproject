# -*- coding: utf-8 -*-
"""统一实验配置：第一阶段不选择 K、不调 C、不使用保留测试集。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
RANDOM_STATE = 42
CV_MODE = "standard"  # standard：5 折；repeated：5 折 × 20 次，仅供固定配置鲁棒性评估。
K_VALUES = (20, 50, 100, 300, 500, 1000)
CLASS_ORDER = ("BRCA", "KIRC", "COAD", "LUAD", "PRAD")


@dataclass(frozen=True)
class ExperimentConfig:
    """不可变配置对象；模块间显式传递，便于记录及复现。"""
    random_state: int = RANDOM_STATE
    test_size: float = 0.2
    cv_mode: str = CV_MODE
    n_splits: int = 5
    n_repeats: int = 20
    k_values: tuple[int, ...] = K_VALUES
    c_grid: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0)
    baseline_c: float = 1.0
    max_iter: int = 50000
    tolerance: float = 1e-4
    class_weight: str | None = None
    n_jobs: int = 1
    numeric_threads: int = 1
    stability_subsamples: int = 30
    stability_fraction: float = 0.8
    expected_samples: int = 801
    expected_features: int = 20531
    data_dir: Path = PROJECT_DIR / "data"
    split_manifest_path: Path = PROJECT_DIR / "data" / "split_manifest.json"
    raw_archive: Path = (PROJECT_DIR.parent / "癌症基因表达数据可视化" /
                         "原始数据" / "TCGA-PANCAN-HiSeq-801x20531.tar")
    output_dir: Path = PROJECT_DIR / "results"

    def to_dict(self) -> dict:
        """路径使用字符串保存到 JSON，实际代码不依赖机器绝对目录。"""
        result = asdict(self)
        for key, value in result.items():
            if isinstance(value, Path):
                result[key] = str(value)
        result["class_order"] = list(CLASS_ORDER)
        return result


if __name__ == "__main__":
    import json
    print(json.dumps(ExperimentConfig().to_dict(), ensure_ascii=False, indent=2))
