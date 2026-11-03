from __future__ import annotations
import csv
import gzip
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from backend.app.lab_config import atomic_json, read_json, DEVELOPMENT_SHA

PROJECT = Path(__file__).resolve().parents[3]
DEFINITIONS = read_json(PROJECT / 'datasets/registry.json')['datasets']

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray
    sample_ids: list[str]
    feature_names: list[str]
    groups: np.ndarray | None
    metadata: dict
    split_protocol: str

class Datasets:
    def __init__(self, project=PROJECT):
        self.project = Path(project)
        self.root = self.project / 'datasets'

    def definition(self, key):
        for item in DEFINITIONS:
            if item['dataset_id'] == key:
                return dict(item)
        raise ValueError('未知数据集')

    def info(self, key):
        item = self.definition(key)
        path = self.root / key / 'metadata.json'
        if path.exists():
            item.update(read_json(path))
        else:
            item.update(status='pending', samples=None, features=None, classes=None, version=None,
                        error='数据集待导入', class_counts={})
        download_record=self.root/key/'raw/download.json'
        if download_record.exists():
            item['download']=read_json(download_record)
        return item

    def list(self):
        return [self.info(d['dataset_id']) for d in DEFINITIONS]

    def import_pancan(self):
        if self.project.resolve() != PROJECT:
            raise ValueError('隔离工作区禁止读取正式PANCAN数据')
        from config import ExperimentConfig
        from backend.app.services.development_data import load_lab_development
        from deployment.lab_registry import SPLIT_SHA
        cfg = ExperimentConfig()
        if digest(cfg.split_manifest_path) != SPLIT_SHA:
            raise ValueError('固定640/161划分摘要不符')
        folder = self.root / 'pancan' / 'audit'
        folder.mkdir(parents=True, exist_ok=True)
        dev = load_lab_development(cfg, folder)
        record = read_json(folder / 'development_data_record.json')
        if record['development_fingerprint_sha256'] != DEVELOPMENT_SHA:
            raise ValueError('开发集指纹不符')
        spec = self.definition('pancan')
        source_hashes={}
        if cfg.raw_archive.is_file():
            source_hashes['raw_archive_sha256']=digest(cfg.raw_archive)
        self.save(spec, dev.X.to_numpy(), dev.y.to_numpy(), list(dev.X.index), list(dev.X.columns), None,
                  {'source':record['source'], 'source_sha256':DEVELOPMENT_SHA, 'split_sha256':SPLIT_SHA, **source_hashes,
                   'reserved_samples_excluded':161, 'reserved_values_parsed':False}, [])
        return self.info('pancan')

    def import_geo(self, key, path):
        spec = self.definition(key)
        if spec['adapter'] != 'geo':
            raise ValueError('PANCAN只能复用固定开发集适配器')
        opener = gzip.open if str(path).endswith('.gz') else open
        metadata, matrix_lines = {}, []
        with opener(path, 'rt', encoding='utf-8-sig') as stream:
            total_bytes = 0
            table = False
            for line in stream:
                total_bytes += len(line)
                if total_bytes > 600 * 1024**2:
                    raise ValueError('解压矩阵超过600 MiB限制')
                if line.startswith('!series_matrix_table_begin'):
                    table = True
                elif line.startswith('!series_matrix_table_end'):
                    table = False
                elif table:
                    matrix_lines.append(line)
                elif line.startswith('!'):
                    row = next(csv.reader([line], delimiter='\t'))
                    metadata.setdefault(row[0], []).append(row[1:])
        if not matrix_lines:
            raise ValueError('Series Matrix没有表达表；需下载processed matrix，不能导入CEL原始文件')
        if metadata.get('!Series_geo_accession', [[None]])[0] != [spec['accession']]:
            raise ValueError('Series accession与所选数据集不一致')
        header = next(csv.reader([matrix_lines[0]], delimiter='\t'))
        if len(header) != len(set(header)):
            raise ValueError('表达矩阵样本ID重复')
        frame = pd.read_csv(io.StringIO(''.join(matrix_lines)), sep='\t', index_col=0)
        ids = metadata.get('!Sample_geo_accession', [[]])[0]
        if not ids or len(ids) != len(set(ids)) or set(frame.columns) != set(ids):
            raise ValueError('官方样本元数据与矩阵列不匹配')
        platforms = set(metadata.get('!Sample_platform_id', [[]])[0])
        if platforms != {spec['platform']}:
            raise ValueError('芯片平台与数据集配置不符，不混合平台')
        rows = []
        for i, sid in enumerate(ids):
            row = {'sample_id':sid, 'title':metadata.get('!Sample_title', [['']*len(ids)])[0][i]}
            for values in metadata.get('!Sample_characteristics_ch1', []):
                value = values[i]
                if ':' in value:
                    name, val = value.split(':', 1)
                    row[name.strip().lower()] = val.strip()
            rows.append(row)
        included, excluded, y, groups = [], [], [], []
        for row in rows:
            label = row.get(spec['label_field'])
            if label in spec['exclude_values']:
                excluded.append({**row, 'reason':spec.get('exclusion_rule', '不属于预设任务')})
                continue
            if label not in spec['label_map']:
                raise ValueError(f"无法确认样本标签：{row['sample_id']} / {label!r}")
            included.append(row)
            y.append(spec['label_map'][label])
            if spec['group_field']:
                group = row.get(spec['group_field'])
                if not group or group in {'--', 'NA', 'N/A'}:
                    raise ValueError('患者分组不可靠，拒绝随机样本划分')
                groups.append(group)
        if len(set(y)) != len(spec['label_map'].values()):
            # Multiple source labels may intentionally map to one target class.
            if set(y) != set(spec['label_map'].values()):
                raise ValueError('导入后任务类别不完整')
        if spec['group_field'] and max(pd.Series(groups).value_counts()) < 2:
            raise ValueError('配对数据没有重复individual id；患者映射未完成')
        selected_ids = [r['sample_id'] for r in included]
        values = frame[selected_ids].T.to_numpy(dtype=float)
        processing = list(dict.fromkeys(v for row in metadata.get('!Sample_data_processing', []) for v in row))
        if not processing:
            raise ValueError('缺少官方预处理说明，拒绝假定表达尺度')
        if spec.get('transform') == 'log2p':
            if np.any(values < 0):
                raise ValueError('GCOS强度出现负值，请检查表达尺度')
            values = np.log2(1 + values)
        provenance = {'source_sha256':digest(path), 'raw_file':Path(path).name,
                      'official_processing':processing, 'annotation_source':f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={spec['platform']}",
                      'probe_mapping':'保留原探针ID；未映射为基因符号', 'sample_metadata':included}
        download_record = self.root/key/'raw/download.json'
        if download_record.is_file():
            provenance['download'] = read_json(download_record)
        self.save(spec, values, y, selected_ids, [str(v) for v in frame.index], groups or None, provenance, excluded)
        return self.info(key)

    def save(self, spec, X, y, ids, features, groups, provenance, excluded):
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or X.shape != (len(y), len(features)) or len(ids)!=len(y) or (groups is not None and len(groups)!=len(y)) or not np.isfinite(X).all():
            raise ValueError('表达矩阵维度无效或包含缺失/无穷值')
        if len(features) != len(set(features)) or len(ids) != len(set(ids)) or min(pd.Series(y).value_counts()) < 2:
            raise ValueError('重复样本/特征或类别样本量不足')
        version = hashlib.sha256((provenance['source_sha256'] + json.dumps(spec, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()[:16]
        folder = self.root / spec['dataset_id'] / version
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'matrix.tmp').open('wb') as stream:
            np.save(stream, X, allow_pickle=False)
        (folder / 'matrix.tmp').replace(folder / 'matrix.npy')
        atomic_json(folder / 'samples.json', {'sample_ids':ids, 'y':list(y), 'groups':list(groups) if groups is not None else None, 'feature_names':features})
        counts = {str(k):int(v) for k,v in pd.Series(y).value_counts().items()}
        meta = {**spec, 'version':version, 'status':'ready', 'error':None, 'samples':len(y), 'features':len(features),
                'classes':len(counts), 'class_counts':counts, 'imported_at':datetime.now(timezone.utc).isoformat(),
                'quality':{'finite':True, 'duplicate_samples':0, 'duplicate_features':0,
                           'constant_features':int(np.sum(np.ptp(X, axis=0)==0)), 'excluded_count':len(excluded),
                           'unique_groups':len(set(groups)) if groups is not None else None,
                           'minimum':float(X.min()), 'maximum':float(X.max()), 'mean':float(X.mean())},
                'provenance':provenance, 'excluded_samples':excluded,
                'matrix_sha256':digest(folder / 'matrix.npy'), 'samples_sha256':digest(folder / 'samples.json')}
        atomic_json(folder / 'metadata.json', meta)
        atomic_json(self.root / spec['dataset_id'] / 'metadata.json', meta)

    def load(self, key, version=None):
        current = self.info(key)
        version = version or current.get('version')
        if not version or not all(c in '0123456789abcdef' for c in version) or len(version) != 16:
            raise ValueError('数据集待导入')
        folder = self.root / key / version
        meta = read_json(folder / 'metadata.json')
        if digest(folder / 'matrix.npy') != meta['matrix_sha256'] or digest(folder / 'samples.json') != meta['samples_sha256']:
            raise ValueError('数据集缓存完整性检查失败，请重新导入')
        sample = read_json(folder / 'samples.json')
        return Dataset(np.load(folder / 'matrix.npy', mmap_mode='r', allow_pickle=False), np.asarray(sample['y']),
                       sample['sample_ids'], sample['feature_names'], np.asarray(sample['groups']) if sample['groups'] else None,
                       meta, meta['split_protocol'])

    def summary(self, key):
        dataset = self.load(key)
        # Exploratory heatmap: variance ranked, label-free; no predictive performance is derived here.
        columns = np.argsort(np.var(dataset.X, axis=0), kind='stable')[-20:]
        matrix = dataset.X[:60, columns].T.copy()
        matrix = (matrix - matrix.mean(axis=1, keepdims=True)) / np.maximum(matrix.std(axis=1, keepdims=True), 1e-12)
        return {**dataset.metadata, 'heatmap':{'samples':dataset.sample_ids[:60], 'features':[dataset.feature_names[i] for i in columns],
                 'values':matrix.tolist(), 'scope':'前60例 × 高方差20特征；仅探索可视化；特征行Z-score'}}
