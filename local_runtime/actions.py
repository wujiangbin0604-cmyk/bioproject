"""命令行数据导入；直接复用经过验证的官方数据适配器。"""
import argparse
import json
from pathlib import Path
from backend.app.platform2.data import Datasets


def main():
    """导入官方文件，失败时返回非零状态，不生成替代数据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('dataset', choices=['pancan', 'gse4290', 'gse44076', 'gse45827'])
    parser.add_argument('--file', type=Path)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    datasets = Datasets()
    if args.dataset == 'pancan':
        if args.file or args.download:
            parser.error('PANCAN复用原固定开发集；请按DATASET_GUIDE放置原始CSV后导入')
        info = datasets.import_pancan()
    else:
        if args.download and args.file:
            parser.error('--download和--file只选一个')
        if args.download:
            from backend.download_geo import download
            download(args.dataset)
        source = args.file or datasets.root / args.dataset / 'raw' / f'{args.dataset.upper()}_series_matrix.txt.gz'
        if not source.is_file():
            parser.error(f'官方矩阵不存在：{source}；可使用--download或--file')
        info = datasets.import_geo(args.dataset, source)
    print(json.dumps({key: info.get(key) for key in ['dataset_id', 'status', 'version', 'samples', 'features', 'class_counts']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
