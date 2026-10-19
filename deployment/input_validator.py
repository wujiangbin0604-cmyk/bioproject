# -*- coding: utf-8 -*-
"""按基因名称验证并重排单样本表达输入。"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
import pandas as pd

InputData: TypeAlias = str | Path | pd.DataFrame
SAMPLE_ID_COLUMN = "sample_id"


def _duplicate_names(names: list[str]) -> list[str]:
    """在线性时间内返回重复列名；避免对每一列重复扫描整个表头。"""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        else:
            seen.add(name)
    return sorted(duplicates)


class InputValidationError(ValueError):
    """输入文件结构、特征或数值不符合部署模型要求。"""


@dataclass(frozen=True)
class ValidatedSample:
    """完成列名校验、数值检查并按模型训练顺序排列的一行数据。"""

    features: pd.DataFrame
    sample_id: str | None
    input_columns_reordered: bool
    input_feature_count: int


def _read_csv(path: Path) -> tuple[pd.DataFrame, list[str]]:
    if not path.exists():
        raise InputValidationError(f"找不到输入文件：{path}")
    if not path.is_file():
        raise InputValidationError(f"输入路径不是文件：{path}")
    if path.suffix.lower() != ".csv":
        raise InputValidationError(f"不支持的文件格式：{path.suffix or '无扩展名'}；请提供CSV文件")
    if path.stat().st_size == 0:
        raise InputValidationError("输入CSV为空文件")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputValidationError(f"无法读取CSV表头，请使用UTF-8编码：{exc}") from exc
    if not header:
        raise InputValidationError("输入CSV缺少表头")
    duplicates = _duplicate_names(header)
    if duplicates:
        raise InputValidationError(f"检测到重复列名：{duplicates[:10]}")
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except (pd.errors.ParserError, UnicodeError, OSError, ValueError) as exc:
        raise InputValidationError(f"CSV格式无法解析：{exc}") from exc
    return frame, header


def validate_single_sample(input_data: InputData, feature_names: tuple[str, ...] | list[str]) -> ValidatedSample:
    """检查单样本表达记录，并根据保存的原始特征名恢复训练列顺序。

    只接受CSV路径或有命名列的DataFrame；有意拒绝无列名的数组，以免列位置错配。
    可选元数据列仅允许 `sample_id`，且绝不传入模型。
    """
    expected = tuple(str(name) for name in feature_names)
    if not expected or len(expected) != len(set(expected)):
        raise InputValidationError("模型特征清单为空或包含重复基因名")
    source_header: list[str]
    if isinstance(input_data, pd.DataFrame):
        # 校验只读取输入，不修改它；免去20,531列DataFrame的整表复制。
        frame = input_data
        source_header = [str(column) for column in frame.columns]
    elif isinstance(input_data, (str, Path)):
        frame, source_header = _read_csv(Path(input_data))
    else:
        raise InputValidationError("输入必须是CSV文件路径或带有基因列名的pandas.DataFrame")

    if not source_header:
        raise InputValidationError("输入表没有任何列")
    duplicates = _duplicate_names(source_header)
    if duplicates:
        raise InputValidationError(f"检测到重复列名：{duplicates[:10]}")
    if any(not isinstance(column, str) or not column for column in frame.columns):
        raise InputValidationError("列名必须是非空字符串")
    if frame.empty:
        raise InputValidationError("输入CSV不包含样本行")
    if len(frame) != 1:
        raise InputValidationError(f"单样本预测要求恰好1行，实际为{len(frame)}行")

    sample_id: str | None = None
    if SAMPLE_ID_COLUMN in frame.columns:
        raw_id = frame.iloc[0][SAMPLE_ID_COLUMN]
        if pd.isna(raw_id) or not str(raw_id).strip():
            raise InputValidationError("sample_id 不能为空")
        sample_id = str(raw_id).strip()

    input_features = tuple(column for column in frame.columns if column != SAMPLE_ID_COLUMN)
    input_set, expected_set = set(input_features), set(expected)
    missing = sorted(expected_set - input_set)
    extra = sorted(input_set - expected_set)
    if missing:
        raise InputValidationError(f"缺少必需基因列（共{len(missing)}个），示例：{missing[:10]}")
    if extra:
        raise InputValidationError(f"存在未识别的额外字段（共{len(extra)}个），示例：{extra[:10]}")
    if len(input_features) != len(expected):
        raise InputValidationError(f"基因特征数量应为{len(expected)}，实际为{len(input_features)}")

    selected_frame = frame.loc[:, list(expected)]
    bool_mask = selected_frame.dtypes.astype(str).isin(("bool", "boolean")).to_numpy()
    if bool_mask.any():
        bool_genes = [expected[i] for i in np.flatnonzero(bool_mask)[:10]]
        raise InputValidationError(f"存在非数值表达值（布尔类型），基因列示例：{bool_genes}")

    # 单样本只有20,531个值：展平后一次批量转换，避免逐基因创建Series。
    raw_values = selected_frame.to_numpy(dtype=object, copy=False).reshape(-1)
    raw_missing = pd.isna(raw_values)
    numeric = pd.to_numeric(pd.Series(raw_values, copy=False), errors="coerce")
    values = numeric.to_numpy(dtype=np.float64, na_value=np.nan, copy=False)
    non_numeric_mask = np.isnan(values) & ~raw_missing
    if non_numeric_mask.any():
        bad_indices = np.flatnonzero(non_numeric_mask)[:10]
        bad_genes = [expected[int(i)] for i in bad_indices]
        raise InputValidationError(f"存在非数值表达值，基因列示例：{bad_genes}")
    if np.isnan(values).any():
        bad_indices = np.flatnonzero(np.isnan(values))[:10]
        missing_genes = [expected[int(i)] for i in bad_indices]
        raise InputValidationError(f"存在NaN或缺失表达值，基因列示例：{missing_genes}")
    finite_mask = np.isfinite(values)
    if not finite_mask.all():
        bad_indices = np.flatnonzero(~finite_mask)[:10]
        bad_columns = [expected[int(i)] for i in bad_indices]
        raise InputValidationError(f"表达值包含正无穷或负无穷，基因列示例：{bad_columns[:10]}")
    ordered = pd.DataFrame(values.reshape(1, -1), columns=expected, index=frame.index)
    reordered = tuple(input_features) != expected
    return ValidatedSample(ordered, sample_id, reordered, len(input_features))
