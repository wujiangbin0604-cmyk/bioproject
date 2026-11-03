from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime, timezone
from uuid import uuid4
import psutil
from backend.app.services.lab_jobs import LabJobs, TaskConflict
from backend.app.lab_config import atomic_json, limits, read_json
from backend.app.services.lab_resources import available_memory_bytes
from .data import PROJECT

class Jobs(LabJobs):
    def __init__(self, project=PROJECT):
        self.project=Path(project)
        super().__init__(self.project/'experiment_runs')
        # Same OS lock as the existing laboratory: legacy and v2 cannot train concurrently.
        self.shared_runner=LabJobs(self.project/'results/lab_experiments')

    def start(self, configuration, payload=None, suffix='.txt.gz'):
        with self.lock:
            if os.getenv('GENESCOPE_LAB_TRAINING_ENABLED','1') != '1':
                raise TaskConflict('当前部署未开放现场计算')
            if available_memory_bytes() < limits()['minimum_available_memory_mb']*1024**2:
                raise TaskConflict('可用内存不足，暂不启动实验')
            self.root.mkdir(parents=True,exist_ok=True)
            if psutil.disk_usage(str(self.root)).free < 1024**3:
                raise TaskConflict('结果目录可用磁盘不足1 GiB')
            if len(self.list()) >= limits()['max_saved_tasks']:
                raise TaskConflict('记录达到上限，请管理员归档')
            guard=self.shared_runner._acquire()
            try:
                key=uuid4().hex
                folder=self.root/key
                folder.mkdir(parents=True)
                if payload is not None:
                    (folder/('upload'+suffix)).write_bytes(payload)
                    configuration={**configuration,'upload_suffix':suffix}
                config=configuration.get('experiment_config',{})
                state={'task_id':key,'dataset_id':configuration['dataset_id'],'kind':configuration['kind'],
                       'configuration':configuration,'experiment_config':config,'dataset_version':configuration.get('dataset_version'),
                       'created_at':datetime.now(timezone.utc).isoformat(),'started_at':None,'finished_at':None,
                       'owner_pid':os.getpid(),'owner_started':psutil.Process().create_time(),'status':'queued','revision':0,
                       'current_stage':'任务已排队','completed_folds':0,'total_folds':config.get('folds',0)*config.get('repeats',1)*len(config.get('algorithms',[])),
                       'progress':0,'elapsed_seconds':0,'folds':[],'metrics':None,'errors':[], 'error':None,'artifact_paths':[]}
                atomic_json(folder/'state.json',state)
                env=os.environ.copy()
                for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:
                    env[name]='1'
                env['PYTHONUTF8']='1'
                with (folder/'worker.log').open('w',encoding='utf-8') as out:
                    process=subprocess.Popen([sys.executable,'-m','backend.app.platform2.worker',str(folder)],cwd=PROJECT,env=env,
                                             stdout=out,stderr=subprocess.STDOUT,
                                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self.processes[key]=process
                threading.Thread(target=self._monitor,args=(key,process,guard),daemon=True).start()
                return state
            except Exception:
                guard.close()
                raise

    def _finish(self,task_id,status,message):
        existing=read_json(self.directory(task_id)/'state.json')
        if existing['status'] in {'completed','failed','cancelled','interrupted'}:
            return existing
        state=super()._finish(task_id,status,message)
        if state['status']==status:
            state.update(finished_at=datetime.now(timezone.utc).isoformat(),current_stage=message,
                         errors=[message] if status=='failed' else state.get('errors',[]))
            atomic_json(self.directory(task_id)/'state.json',state)
        return state

    def get(self,task_id):
        state=super().get(task_id)
        if state['status']=='interrupted':
            state.update(status='failed',current_stage='服务重启使任务中断；已有结果已保存',errors=['工作进程已停止'])
            atomic_json(self.directory(task_id)/'state.json',state)
        return state

    def cancel(self,task_id):
        with self.lock:
            state=self.get(task_id)
            if state['status'] in {'completed','failed','cancelled'}:
                return state
            state.update(status='cancel_requested',revision=state['revision']+1,current_stage='正在停止工作进程')
            atomic_json(self.directory(task_id)/'state.json',state)
            return super().cancel(task_id)
