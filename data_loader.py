# -*- coding: utf-8 -*-
"""原始 CSV/TAR 读取、质量检查、固定分层划分；第一阶段只返回开发集。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype
from sklearn.model_selection import train_test_split

from config import CLASS_ORDER, ExperimentConfig


def write_json(path: Path, payload: dict) -> None:
    """使用 UTF-8 输出 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


@dataclass
class RawDataset:
    X: pd.DataFrame
    y: pd.Series
    quality: dict
    fingerprint: str


@dataclass
class DevelopmentData:
    """后续交叉验证只接受此对象；不包含测试集表达矩阵或测试标签。"""
    X: pd.DataFrame
    y: pd.Series
    reserved_test_ids: tuple[str, ...]
    fingerprint: str
    split_manifest_path: Path


def _check_header(stream, name: str) -> None:
    """先检查原始表头，避免 pandas 自动重命名掩盖重复基因列。"""
    first = stream.readline()
    text = first.decode("utf-8-sig") if isinstance(first, bytes) else first.lstrip("\ufeff")
    header = next(csv.reader([text]))
    if len(header) < 2:
        raise ValueError(f"{name} 未识别为至少两列的逗号分隔 CSV，请检查实际文件结构")
    if len(set(header)) != len(header):
        raise ValueError(f"{name} 的原始表头存在重复列名")


def _read_frames(cfg: ExperimentConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """优先读项目 data 下的两个 CSV；否则流式读 TAR 任意层级成员。"""
    data_path, labels_path = cfg.data_dir / "data.csv", cfg.data_dir / "labels.csv"
    if data_path.is_file() != labels_path.is_file():
        raise FileNotFoundError("data 目录中 data.csv 与 labels.csv 必须同时提供")
    if data_path.is_file():
        for path in (data_path, labels_path):
            with path.open("rb") as stream:
                _check_header(stream, path.name)
        return (pd.read_csv(data_path, encoding="utf-8-sig"),
                pd.read_csv(labels_path, encoding="utf-8-sig"),
                {"format": "csv", "data": str(data_path), "labels": str(labels_path)})
    archive = cfg.raw_archive
    if not archive.is_file():
        raise FileNotFoundError(f"未找到两个 CSV 或配置的 TAR：{archive}；请查看 data/README.md")
    with tarfile.open(archive, "r:*") as tar:
        members = {}
        for name in ("data.csv", "labels.csv"):
            found = [m for m in tar.getmembers() if m.isfile() and
                     PurePosixPath(m.name).name.lower() == name]
            if len(found) != 1:
                raise ValueError(f"TAR 中应有唯一 {name}，找到 {len(found)} 个")
            members[name] = found[0]
            with tar.extractfile(found[0]) as stream:
                _check_header(stream, name)
        with tar.extractfile(members["data.csv"]) as stream:
            X = pd.read_csv(stream, encoding="utf-8-sig")
        with tar.extractfile(members["labels.csv"]) as stream:
            y = pd.read_csv(stream, encoding="utf-8-sig")
    return X, y, {"format": "tar", "archive": str(archive),
                  "members": {key: value.name for key, value in members.items()}}


def _sample_column(frame: pd.DataFrame, name: str) -> str:
    candidates = [c for c in frame if str(c).lower() in
                  ("unnamed: 0", "sample_id", "sample", "id")]
    candidates += [frame.columns[0]]
    for col in dict.fromkeys(candidates):
        ids = frame[col].astype("string")
        if ids.notna().all() and ids.str.fullmatch(r"sample_\d+").all():
            return col
    raise ValueError(f"{name} 找不到可确认的 sample_* ID 列，实际前几列 {list(frame.columns[:5])}")


def load_raw_data(cfg: ExperimentConfig) -> RawDataset:
    """只做格式/完整性检查，不在全数据上拟合标准化、填补或特征选择。"""
    raw_X, raw_y, source = _read_frames(cfg)
    xid, yid = _sample_column(raw_X, "data.csv"), _sample_column(raw_y, "labels.csv")
    ids = pd.Index(raw_X[xid].astype(str), name="sample_id")
    label_ids = pd.Index(raw_y[yid].astype(str), name="sample_id")
    if ids.has_duplicates or label_ids.has_duplicates:
        raise ValueError("表达矩阵或标签存在重复样本 ID，必须先核实，不能随机拆分重复个体")
    if set(ids) != set(label_ids):
        raise ValueError("表达矩阵与标签的样本 ID 集合不一致")
    if "Class" not in raw_y:
        raise ValueError(f"标签文件缺少 Class 列，实际列为 {list(raw_y.columns)}")
    if raw_y["Class"].isna().any():
        raise ValueError("标签文件有缺失类别")
    X = raw_X.drop(columns=xid).set_axis(ids)
    if X.columns.has_duplicates or any(not str(c).startswith("gene_") for c in X):
        raise ValueError("表达特征列异常，基因列名必须唯一并保留 gene_* 原始名称")
    nonnumeric = [c for c in X if not is_numeric_dtype(X[c].dtype)]
    if nonnumeric:
        raise ValueError(f"发现非数值特征列：{nonnumeric[:10]}")
    values = X.to_numpy(dtype=np.float64, copy=False)
    missing, infinite = int(np.isnan(values).sum()), int(np.isinf(values).sum())
    if missing or infinite:
        raise ValueError(f"表达矩阵有缺失值 {missing} / 无穷值 {infinite}；本阶段不自动填补")
    y = pd.Series(raw_y["Class"].astype(str).to_numpy(), index=label_ids,
                  name="cancer_type").reindex(ids)
    if set(y) != set(CLASS_ORDER):
        raise ValueError(f"类别集合异常：{sorted(set(y))}")
    if X.shape != (cfg.expected_samples, cfg.expected_features):
        raise ValueError(f"数据维度为 {X.shape}，与预期 {(cfg.expected_samples, cfg.expected_features)} 不符")
    # 表达谱重复也要检查；若存在则停止，不能让相同表达谱跨开发/测试集。
    row_hashes = [hashlib.sha256(np.asarray(row, dtype="<f8").tobytes()).digest() for row in values]
    duplicates = len(row_hashes) - len(set(row_hashes))
    if duplicates:
        raise ValueError(f"发现 {duplicates} 个完全重复表达谱，请先核实个体及分组划分策略")
    digest = hashlib.sha256()
    digest.update(json.dumps(list(X.columns), ensure_ascii=False).encode("utf-8"))
    for sid, label, row_hash in zip(ids, y, row_hashes):
        digest.update(json.dumps([sid, label]).encode("utf-8"))
        digest.update(row_hash)
    fingerprint = digest.hexdigest()
    quality = {
        "source": source, "n_samples": len(X), "n_genes": X.shape[1],
        "n_classes": y.nunique(), "missing_values": missing, "infinite_values": infinite,
        "duplicate_expression_ids": int(ids.duplicated().sum()),
        "duplicate_label_ids": int(label_ids.duplicated().sum()),
        "duplicate_expression_profiles": duplicates, "nonnumeric_columns": len(nonnumeric),
        "original_order_matches": ids.equals(label_ids), "labels_aligned_by_id": True,
        "dtype_counts": {str(k): int(v) for k, v in X.dtypes.astype(str).value_counts().items()},
        "class_counts": {key: int(y.eq(key).sum()) for key in CLASS_ORDER},
        "dataset_fingerprint_sha256": fingerprint,
        "global_preprocessing_fitted": False,
    }
    return RawDataset(X, y, quality, fingerprint)


def prepare_development_data(cfg: ExperimentConfig, run_dir: Path) -> DevelopmentData:
    """固定 80/20 分层划分并持久化；只向开发实验返回开发集。"""
    raw = load_raw_data(cfg)
    train_ids, test_ids = train_test_split(
        raw.X.index.to_numpy(), test_size=cfg.test_size, stratify=raw.y.to_numpy(),
        random_state=cfg.random_state,
    )
    manifest = {
        "schema_version": 1, "dataset_fingerprint_sha256": raw.fingerprint,
        "random_state": cfg.random_state, "test_size": cfg.test_size,
        "development_ids": train_ids.tolist(), "reserved_test_ids": test_ids.tolist(),
        "test_evaluation_performed": False,
    }
    manifest_path = cfg.split_manifest_path
    if manifest_path.is_file():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(saved.get(k) != manifest[k] for k in manifest):
            raise ValueError("固定划分清单与当前数据/配置不一致；为避免无意更换测试集，本次停止")
    else:
        write_json(manifest_path, manifest)
    assert not set(train_ids) & set(test_ids)
    assert set(train_ids) | set(test_ids) == set(raw.X.index)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "data_quality.json", raw.quality)
    write_json(run_dir / "split_manifest.json", manifest)
    split_rows = []
    for subset, sample_ids in (("all_quality_check_only", raw.X.index),
                               ("development", train_ids), ("reserved_test", test_ids)):
        counts = raw.y.loc[sample_ids].value_counts().reindex(CLASS_ORDER, fill_value=0)
        for label, count in counts.items():
            split_rows.append({"subset": subset, "cancer_type": label,
                               "n_samples": int(count), "percentage": float(count / len(sample_ids) * 100)})
    pd.DataFrame(split_rows).to_csv(run_dir / "class_distribution.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"gene_id": raw.X.columns, "dtype": raw.X.dtypes.astype(str).to_numpy()}).to_csv(
        run_dir / "gene_columns.csv", index=False, encoding="utf-8-sig")
    # 这里 copy 原始表达值，仅截取行；没有拟合任何统计变换。
    return DevelopmentData(raw.X.loc[train_ids].copy(), raw.y.loc[train_ids].copy(),
                           tuple(test_ids), raw.fingerprint, manifest_path)


def load_final_test(*args, **kwargs):
    """第五阶段预留；本阶段不提供测试集评分通道。"""
    raise NotImplementedError("最终模型尚未冻结；第五阶段的保留测试集加载与评估入口暂未启用")


def _read_development_rows_only(cfg: ExperimentConfig, development_ids: list[str],
                                reserved_ids: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """只把开发行交给pandas解析；保留行仅核对首列ID，其表达值/标签不解析。

    TAR/CSV顺序读取仍需经过文件字节；这不是把保留行加载成表达矩阵。
    明确验证本数据的单行数值CSV结构，遇到其他格式停止而不猜测。
    """
    keep, expected = set(development_ids), set(development_ids) | set(reserved_ids)

    def filtered(stream, name):
        header_line = stream.readline().decode("utf-8-sig")
        header = next(csv.reader([header_line]))
        valid_header = (header[1:] == [f"gene_{i}" for i in range(20531)] if name == "data.csv"
                        else header[1:] == ["Class"])
        if not valid_header or header[0].lower() not in ("", "unnamed: 0", "sample_id", "sample", "id"):
            raise ValueError(f"{name}实际表头不符合已检查的首列样本ID结构，请先检查格式")
        if len(set(header)) != len(header):
            raise ValueError(f"{name}表头重复")
        selected, seen = [header_line], set()
        import re
        for raw_line in stream:
            # 仅解码首个分隔符之前的ID；保留样本后面的字节不解析成特征/类别。
            sid_token = raw_line.partition(b",")[0].decode("utf-8")
            sid = next(csv.reader([sid_token]))[0]
            if re.fullmatch(r"sample_\d+", sid) is None or sid in seen:
                raise ValueError(f"{name}存在异常/重复ID或多行CSV结构")
            seen.add(sid)
            if sid in keep:
                selected.append(raw_line.decode("utf-8"))
        if seen != expected or len(selected) != 641:
            raise ValueError(f"{name}样本ID集合与固定640/161清单不同")
        frame = pd.read_csv(io.StringIO("".join(selected)))
        if len(frame) != 640:
            raise ValueError("开发行筛选后维度错误")
        return frame

    data_path, label_path = cfg.data_dir / "data.csv", cfg.data_dir / "labels.csv"
    if data_path.is_file() != label_path.is_file():
        raise FileNotFoundError("data.csv和labels.csv必须同时提供")
    if data_path.is_file():
        with data_path.open("rb") as xs, label_path.open("rb") as ys:
            X, y = filtered(xs, "data.csv"), filtered(ys, "labels.csv")
        return X, y, {"format": "csv", "data": str(data_path), "labels": str(label_path),
                      "development_rows_only_parsed": True}
    with tarfile.open(cfg.raw_archive, "r:*") as tar:
        members = {}
        for name in ("data.csv", "labels.csv"):
            matches = [m for m in tar.getmembers() if m.isfile() and PurePosixPath(m.name).name.lower() == name]
            if len(matches) != 1:
                raise ValueError(f"TAR中{name}不是唯一成员")
            members[name] = matches[0]
        with tar.extractfile(members["data.csv"]) as xs:
            X = filtered(xs, "data.csv")
        with tar.extractfile(members["labels.csv"]) as ys:
            y = filtered(ys, "labels.csv")
    return X, y, {"format": "tar", "archive": str(cfg.raw_archive),
                  "members": {k: v.name for k, v in members.items()}, "development_rows_only_parsed": True}


def load_existing_development_data(cfg: ExperimentConfig, run_dir: Path, *,
                                    strict_rows_only: bool = False) -> DevelopmentData:
    """复用已有划分，读取后立即截取开发行；不分析保留样本的表达或标签。

    TAR/CSV文件物理上包含801行，但只有固定640行被传入数据检查和模型。
    不重新 train_test_split，不重新统计161个保留样本的类别或表达分布。
    """
    if not cfg.split_manifest_path.is_file():
        raise FileNotFoundError("缺少第一阶段固定划分清单，不能为重复CV临时重新划分")
    manifest = json.loads(cfg.split_manifest_path.read_text(encoding="utf-8"))
    dev_ids, reserved_ids = manifest["development_ids"], manifest["reserved_test_ids"]
    if (len(dev_ids), len(reserved_ids)) != (640, 161):
        raise ValueError("已有划分不是640/161")
    if manifest["random_state"] != 42 or manifest["test_size"] != 0.2:
        raise ValueError("已有划分参数与原实验不一致")
    if len(set(dev_ids)) != 640 or len(set(reserved_ids)) != 161 or set(dev_ids) & set(reserved_ids):
        raise ValueError("固定划分的样本ID重复或交叉")
    raw_X, raw_y, source = (_read_development_rows_only(cfg, dev_ids, reserved_ids)
                            if strict_rows_only else _read_frames(cfg))
    xid, yid = _sample_column(raw_X, "data.csv"), _sample_column(raw_y, "labels.csv")
    if raw_X[xid].duplicated().any() or raw_y[yid].duplicated().any():
        raise ValueError("源文件存在重复样本ID")
    expected_ids = set(dev_ids) if strict_rows_only else set(dev_ids) | set(reserved_ids)
    if set(raw_X[xid]) != expected_ids:
        raise ValueError("原始样本ID集合已发生变化")
    if set(raw_y[yid]) != set(raw_X[xid]):
        raise ValueError("原始表达与标签ID集合不一致")
    X = raw_X.set_index(xid).loc[dev_ids].copy()
    if "Class" not in raw_y:
        raise ValueError("标签文件缺少Class列")
    y = raw_y.set_index(yid).loc[dev_ids, "Class"].copy()
    del raw_X, raw_y
    X.index.name = y.index.name = "sample_id"
    y.name = "cancer_type"
    if X.shape != (640, 20531) or list(X.columns) != [f"gene_{i}" for i in range(20531)]:
        raise ValueError("开发集维度或原始基因列顺序异常")
    if any(not is_numeric_dtype(X[c].dtype) for c in X):
        raise ValueError("开发集存在非数值特征")
    if not np.isfinite(X.to_numpy(dtype=float)).all() or y.isna().any():
        raise ValueError("开发集存在缺失或无穷值")
    y = y.astype(str)
    if set(y) != set(CLASS_ORDER):
        raise ValueError("开发集类别异常")
    digest = hashlib.sha256()
    digest.update(json.dumps(list(X.columns)).encode("utf-8"))
    for sid, label, row in zip(X.index, y, X.to_numpy(dtype=float)):
        digest.update(json.dumps([sid, label]).encode("utf-8"))
        digest.update(np.asarray(row, dtype="<f8").tobytes())
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "split_manifest.json", manifest)
    write_json(run_dir / "development_data_record.json", {
        "source": source, "n_development": 640, "n_features": 20531,
        "n_reserved_excluded": 161, "original_dataset_fingerprint_from_manifest":
        manifest["dataset_fingerprint_sha256"], "development_fingerprint_sha256": digest.hexdigest(),
        "reserved_values_analyzed": False, "reserved_labels_analyzed": False,
        "strict_development_rows_only_parsed": strict_rows_only,
        "development_class_counts": {c: int(y.eq(c).sum()) for c in CLASS_ORDER},
    })
    return DevelopmentData(X, y, tuple(reserved_ids), manifest["dataset_fingerprint_sha256"],
                           cfg.split_manifest_path)


if __name__ == "__main__":
    raw = load_raw_data(ExperimentConfig())
    print(json.dumps(raw.quality, ensure_ascii=False, indent=2))
