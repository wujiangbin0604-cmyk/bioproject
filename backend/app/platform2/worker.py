import os
for variable in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
    os.environ[variable]='1'
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
import traceback
import psutil
from backend.app.lab_config import atomic_json, read_json
from .data import Datasets

def run(folder):
    state=read_json(folder/'state.json')
    project=folder.parent.parent
    datasets=Datasets(project)
    lock=threading.RLock()
    def publish(**values):
        with lock:
            state.update(values)
            state['revision']+=1
            state['elapsed_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(state['created_at'])).total_seconds()
            atomic_json(folder/'state.json',state)
            with (folder/'events.jsonl').open('a',encoding='utf-8') as stream:
                import json
                stream.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'stage':state['current_stage'],'status':state['status'],'completed_folds':state['completed_folds']},ensure_ascii=False)+'\n')
    def owner_watch():
        while True:
            time.sleep(1)
            if state['status'] in {'completed','failed','cancelled'}:
                return
            try:
                alive=psutil.Process(state['owner_pid']).create_time()==state['owner_started']
            except psutil.Error:
                alive=False
            if not alive:
                publish(status='failed',current_stage='API所有者停止，终止无监控计算',finished_at=datetime.now(timezone.utc).isoformat())
                os._exit(2)
    threading.Thread(target=owner_watch,daemon=True).start()
    try:
        publish(status='preparing',started_at=datetime.now(timezone.utc).isoformat(),current_stage='核验数据与实验协议',worker_pid=os.getpid())
        config=state['configuration']
        key=state['dataset_id']
        if config['kind']=='import':
            if key=='pancan':
                info=datasets.import_pancan()
            else:
                if config.get('download'):
                    from backend.download_geo import download
                    download(key)
                source=folder/('upload'+config['upload_suffix']) if config.get('upload_suffix') else datasets.root/key/'raw'/f'{key.upper()}_series_matrix.txt.gz'
                if not source.is_file():
                    raise ValueError('官方矩阵尚未下载；可重试下载或上传本地Series Matrix')
                info=datasets.import_geo(key,source)
            atomic_json(folder/'results.json',{'dataset':info})
            publish(status='completed',progress=100,current_stage='导入已完成',finished_at=datetime.now(timezone.utc).isoformat())
        else:
            from .engine import ExperimentConfig, train
            dataset=datasets.load(key,config['dataset_version'])
            result=train(dataset,ExperimentConfig(**config['experiment_config']),folder,publish,project/'model_registry')
            publish(status='completed',progress=100,current_stage='实验已完成',finished_at=datetime.now(timezone.utc).isoformat(),
                    metrics=[{'algorithm':r['algorithm'],'metrics':r['metrics']} for r in result['results']],artifact_paths=['results.json','folds.json','split_indices.json'])
    except Exception as exc:
        traceback.print_exc()
        error=f'{type(exc).__name__}: {exc}'
        if state['kind']=='import' and datasets.info(state['dataset_id'])['status']!='ready':
            atomic_json(datasets.root/state['dataset_id']/'metadata.json',{'status':'pending','error':error,'samples':None,'features':None,'classes':None,'version':None})
        publish(status='failed',current_stage='任务失败',error=error,errors=[error],finished_at=datetime.now(timezone.utc).isoformat())

if __name__=='__main__':
    run(Path(sys.argv[1]))
