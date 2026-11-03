"""Standard-library release verification and non-destructive persistent-state initialization."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()

def seed_file(relative):
    p=PurePosixPath(relative)
    return p.parts[0] in {'experiment_runs','model_registry','development_data'} or (p.parts[0]=='datasets' and relative!='datasets/registry.json')

def verify(root=ROOT,code_only=False):
    root=Path(root).resolve()
    manifest=json.loads((root/'genescope2_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version')!=2 or manifest.get('pancan_reserved_expression_included') is not False:
        raise ValueError('发布范围标记不符')
    checked=0
    for relative,expected in manifest['files'].items():
        p=PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or ':' in relative or '\\' in relative:
            raise ValueError('发布清单含不安全路径')
        if code_only and seed_file(relative):
            continue
        target=root.joinpath(*p.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file() or sha(target)!=expected:
            raise ValueError(f'发布文件缺失或摘要不同：{relative}')
        checked+=1
    print(f'GeneScope 2 release integrity: OK ({checked} files)',flush=True)
    return manifest

def initialize(root=ROOT,state=Path('/opt/genescope/state-v2')):
    if Path(state).is_symlink():
        raise ValueError('持久化目录不能是符号链接')
    root,state=Path(root).resolve(),Path(state).resolve()
    verify(root)
    if state==root or state.is_relative_to(root) or state==Path(state.anchor):
        raise ValueError('持久化目录必须独立于发布目录')
    marker=state/'.genescope2-state.json'
    if state.exists() and any(state.iterdir()) and not marker.is_file():
        raise ValueError('非空目录缺少GeneScope状态标记，拒绝修改')
    state.mkdir(parents=True,exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({'application':'GeneScope2','schema_version':2}),encoding='utf-8')
    copied=0
    for folder in ['datasets','experiment_runs','model_registry','development_data']:
        for source in (root/folder).rglob('*'):
            if not source.is_file():
                continue
            relative=source.relative_to(root)
            target=state/relative
            if target.is_symlink() or not target.resolve().is_relative_to(state):
                raise ValueError('状态目录包含不安全链接')
            if target.exists():
                # Existing state belongs to the server. Never overwrite models, tasks or data.
                if source.name=='registry.json' and sha(source)!=sha(target):
                    raise ValueError('现有数据集定义不同，请先人工核对升级，不覆盖原状态')
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            copied+=1
    (state/'legacy_tasks').mkdir(exist_ok=True)
    # Reuse the exact 640-row cache through a hard link: no reserved values and no second matrix copy.
    meta=json.loads((state/'datasets/pancan/metadata.json').read_text(encoding='utf-8'))
    matrix=state/'datasets/pancan'/meta['version']/'matrix.npy'
    development=state/'development_data/development.npy'
    if not development.exists():
        try:
            os.link(matrix,development)
        except OSError:
            shutil.copyfile(matrix,development)
    if sha(development)!=meta['matrix_sha256']:
        raise ValueError('640例开发包摘要不一致，拒绝启用训练')
    if os.name=='posix' and os.geteuid()==0:
        os.chown(state,10001,10001)
        for folder in ['datasets','experiment_runs','model_registry','development_data','legacy_tasks']:
            for path in [state/folder,*(state/folder).rglob('*')]:
                if path.is_symlink():
                    raise ValueError('持久化目录含符号链接')
                os.chown(path,10001,10001)
    print(json.dumps({'persistent_state':str(state),'new_files':copied,'existing_files_overwritten':False},ensure_ascii=False),flush=True)

def runtime_check(root=ROOT):
    from backend.app.platform2.data import Datasets
    from backend.app.platform2.models import Models
    from deployment.lab_registry import model_statuses
    from deployment.predict import predict_single_sample
    import pandas as pd
    datasets=Datasets(root)
    info=datasets.list()
    if len(info)!=4 or any(d['status']!='ready' for d in info):
        raise ValueError('四数据集未全部就绪')
    statuses=model_statuses()
    if len(statuses)!=6 or not all(m['available'] for m in statuses):
        raise ValueError('原六模型校验未通过，不绕过摘要或运行环境检查')
    registry=Models(Path(root))
    registered=registry.list()
    for key in ['pancan','gse4290','gse44076','gse45827']:
        data=datasets.load(key)
        frame=pd.DataFrame([data.X[0]],columns=data.feature_names)
        frame.insert(0,'sample_id',data.sample_ids[0])
        models=[m for m in registered if m['dataset_id']==key]
        if not models:
            raise ValueError(f'{key}没有注册模型')
        registry.predict(models[0]['model_id'],key,frame.to_csv(index=False).encode())
        if key=='pancan':
            predict_single_sample(frame)
    print(json.dumps({'runtime_check':'passed','ready_datasets':4,'registered_models':len(registered),'frozen_models':6,'holdout_reevaluated':False},ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['verify','initialize','runtime'])
    parser.add_argument('--code-only',action='store_true')
    parser.add_argument('--models',action='store_true')
    parser.add_argument('--state',type=Path,default=Path('/opt/genescope/state-v2'))
    args=parser.parse_args()
    if args.action=='initialize':
        initialize(state=args.state)
    elif args.action=='runtime':
        runtime_check()
    else:
        verify(code_only=args.code_only)
        if args.models:
            from deployment.lab_registry import model_statuses
            statuses=model_statuses()
            if len(statuses)!=6 or not all(x['available'] for x in statuses):
                raise ValueError('冻结模型校验失败')
