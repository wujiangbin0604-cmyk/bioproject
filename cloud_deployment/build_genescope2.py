"""White-listed private server bundle. Large data and generated models never enter Git."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import zipfile
from cloud_deployment.platform2_release import sha,verify

ROOT=Path(__file__).resolve().parents[1]

def build(release):
    if not release.replace('_','').replace('-','').isalnum() or len(release)>100:
        raise ValueError('发布名仅允许字母数字、下划线、连字符')
    destination=ROOT/'cloud_deployment/dist'/release
    archive=destination.with_suffix('.zip')
    if destination.exists() or archive.exists():
        raise ValueError('发布目录已存在，请使用新的发布名')
    from backend.app.platform2.data import Datasets
    from backend.app.platform2.models import Models
    from backend.app.services.results import RUNS,FILES,ResultsRepository
    from deployment.lab_registry import model_statuses,CUSTOM_SOURCE_SHA
    statuses=model_statuses()
    if len(statuses)!=6 or not all(m['available'] for m in statuses):
        raise ValueError('原冻结六模型必须先通过校验')
    datasets=Datasets()
    data_info=datasets.list()
    if any(d['status']!='ready' for d in data_info):
        raise ValueError('四数据集必须导入后再打完整部署包')
    destination.mkdir(parents=True)
    def copy(source,relative=None):
        source=Path(source)
        relative=Path(relative or source.relative_to(ROOT))
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT) or not source.is_file() or relative.is_absolute() or '..' in relative.parts:
            raise ValueError('打包路径无效')
        target=destination/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        if sha(source)!=sha(target):
            raise ValueError('复制后摘要不同')
    for p in ROOT.glob('*.py'):
        copy(p)
    for folder in ['backend/app','deployment']:
        entries=(ROOT/folder).rglob('*.py') if folder=='backend/app' else (ROOT/folder).glob('*.py')
        for p in entries:
            copy(p)
    for folder in ['deployment/models','deployment/lab_models','frontend/dist']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file():
                copy(p)
    for name in ['backend/__init__.py','backend/download_geo.py','backend/import_datasets.py','backend/requirements-web-runtime.lock.txt',
                 'data/split_manifest.json','datasets/registry.json','deployment/examples/sample_input.csv',
                 'cloud_deployment/__init__.py','cloud_deployment/serve.py','cloud_deployment/serve2.py',
                 'cloud_deployment/verify.py','cloud_deployment/public_gateway.py','cloud_deployment/platform2_release.py',
                 'cloud_deployment/platform2_gateway.py','cloud_deployment/requirements-cloud.lock.txt',
                 'cloud_deployment/Dockerfile.genescope2','cloud_deployment/GENESCOPE2_SERVER.md']:
        copy(ROOT/name)
    copy(ROOT/'cloud_deployment/compose.genescope2.yaml','compose.genescope2.yaml')
    # Nginx keeps API streaming unbuffered and only the dataset-import route permits large uploads.
    nginx=(ROOT/'cloud_deployment/nginx.conf').read_text(encoding='utf-8')
    location='''        location = /api/v1/datasets/import {
            client_max_body_size 101m;
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-For "";
            proxy_set_header X-Forwarded-Proto "";
            proxy_request_buffering off;
            proxy_buffering off;
            proxy_read_timeout 120s;
        }
'''
    (destination/'cloud_deployment/nginx.conf').write_text(nginx.replace('        location /api/ {',location+'        location /api/ {'),encoding='utf-8')
    for info in data_info:
        key,version=info['dataset_id'],info['version']
        datasets.load(key)  # Validate complete cache hashes before copying.
        for name in ['matrix.npy','samples.json','metadata.json']:
            copy(ROOT/'datasets'/key/version/name)
        copy(ROOT/'datasets'/key/'metadata.json')
        download=ROOT/'datasets'/key/'raw/download.json'
        if download.exists():
            copy(download)
    pancan=datasets.load('pancan')
    development={'schema_version':1,'shape':[640,20531],'dtype':'float64','sample_ids':pancan.sample_ids,
                 'labels':pancan.y.tolist(),'gene_ids':pancan.feature_names,'matrix_file_sha256':pancan.metadata['matrix_sha256'],
                 'development_fingerprint_sha256':pancan.metadata['provenance']['source_sha256'],
                 'reserved_expression_included':False,'reserved_labels_included':False,'preprocessing_fitted':False}
    (destination/'development_data').mkdir()
    (destination/'development_data/development_metadata.json').write_text(json.dumps(development,ensure_ascii=False),encoding='utf-8')
    registered=Models(ROOT).list()
    tasks=set()
    for model in registered:
        for name in ['pipeline.joblib','metadata.json']:
            copy(ROOT/'model_registry'/model['model_id']/name)
        tasks.add(model['source_experiment_id'])
    for key in tasks:
        for name in ['state.json','results.json','folds.json','split_indices.json','events.jsonl','resource_usage.json']:
            p=ROOT/'experiment_runs'/key/name
            if p.exists():
                copy(p)
    repo=ResultsRepository(ROOT)
    for key,spec in RUNS.items():
        if repo._run(key) is None:
            raise ValueError(f'缺少已保存历史汇总：{key}')
        target=destination/'results'/spec['pointer']
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps({'status':'complete','run_directory':f'history/{key}',
                                     'source_pointer_sha256':sha(ROOT/'results'/spec['pointer'])},ensure_ascii=False),encoding='utf-8')
    for _,spec in FILES.items():
        copy(repo._file(_),Path('results/history')/spec['run']/spec['path'])
    for method in ['variance','anova']:
        source=repo.heatmap_path(method)
        copy(source,Path('results/history/heatmaps/生成图片')/source.name)
    for name,expected in CUSTOM_SOURCE_SHA.items():
        if sha(destination/name)!=expected:
            raise ValueError('冻结自定义类型源码摘要不同')
    (destination/'.dockerignore').write_text('.git\n.env\n.env.*\n**/__pycache__\n**/*.pyc\n**/node_modules\n**/.vendor*\n*.zip\ndatasets/*/\ndevelopment_data/\nexperiment_runs/\nmodel_registry/\nresults/lab_experiments/\n',encoding='utf-8')
    manifest={'schema_version':2,'release':release,'created_at':datetime.now(timezone.utc).isoformat(),
              'pancan_reserved_expression_included':False,'raw_expression_archives_included':False,
              'datasets':[{'dataset_id':d['dataset_id'],'version':d['version'],'samples':d['samples'],'features':d['features']} for d in data_info],
              'registered_models':len(registered),'completed_experiments':len(tasks),
              'files':{str(p.relative_to(destination)).replace('\\','/'):sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}}
    (destination/'genescope2_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    verify(destination)
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=3) as output:
        for p in sorted(destination.rglob('*')):
            if p.is_file():
                output.write(p,str(p.relative_to(destination)).replace('\\','/'))
    checksum=sha(archive)
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':checksum,'datasets':4,
                      'models':len(registered),'completed_experiments':len(tasks),'linux_container_verified':False},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--release',default='GeneScope2_20261103_v1')
    build(parser.parse_args().release)
