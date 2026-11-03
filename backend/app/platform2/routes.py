import asyncio
import io
import json
from typing import Literal
from fastapi import APIRouter, Request, File, Form, UploadFile, Query, HTTPException
from fastapi.responses import Response, StreamingResponse
import pandas as pd
from pydantic import BaseModel, ConfigDict
from backend.app.lab_config import read_json
from backend.app.lab_routes import local_mutation
from backend.app.services.lab_jobs import TaskConflict
from .engine import ALGORITHMS, METHODS, ExperimentConfig
from .models import Models

router=APIRouter(prefix='/api/v1',tags=['GeneScope 2.0'])
TERMINAL={'completed','failed','cancelled'}

class Snapshot(BaseModel):
    model_config=ConfigDict(extra='allow')
    task_id:str
    dataset_id:str
    status:Literal['queued','preparing','running','completed','failed','cancel_requested','cancelled']

class Items(BaseModel):
    items:list[dict]

class DatasetInfo(BaseModel):
    model_config=ConfigDict(extra='allow')
    dataset_id:str
    name:str
    status:Literal['ready','pending']
    samples:int|None=None
    features:int|None=None
    classes:int|None=None
    version:str|None=None

class DatasetItems(BaseModel):
    items:list[DatasetInfo]

class ResultSchema(BaseModel):
    model_config=ConfigDict(extra='allow')
    dataset_id:str|None=None
    dataset:dict|None=None

class ModelInfo(BaseModel):
    model_config=ConfigDict(extra='allow')
    model_id:str
    dataset_id:str
    dataset_version:str
    algorithm:str
    model_version:str
    feature_names:list[str]

class FeatureSchema(BaseModel):
    dataset_id:str
    items:list[dict]
    overlap:list[dict]
    scope:str

def state(request,key):
    try:
        return request.app.state.platform_jobs.get(key)
    except FileNotFoundError as exc:
        raise HTTPException(404,'任务不存在') from exc

def detail(request,key):
    task=state(request,key)
    path=request.app.state.platform_jobs.directory(key)/'results.json'
    if task['status']!='completed' or not path.exists():
        raise HTTPException(409,'实验尚未完成；请查看任务状态及错误')
    return read_json(path)

def start(request,config,payload=None,suffix='.txt.gz'):
    local_mutation(request)
    try:
        return request.app.state.platform_jobs.start(config,payload,suffix)
    except TaskConflict as exc:
        raise HTTPException(409,str(exc)) from exc

@router.get('/datasets',response_model=DatasetItems)
def datasets(request:Request):
    return {'items':request.app.state.datasets.list()}

@router.post('/datasets/import',response_model=Snapshot,status_code=202)
def import_dataset(request:Request,dataset_id:str=Form(...),download:bool=Form(False),file:UploadFile|None=File(None)):
    local_mutation(request)
    try:
        request.app.state.datasets.definition(dataset_id)
        payload=None
        suffix='.txt.gz'
        if file:
            try:
                filename=file.filename or ''
                if not filename.lower().endswith(('.txt','.txt.gz')):
                    raise ValueError('仅接受官方Series Matrix .txt或.txt.gz')
                suffix='.txt.gz' if filename.lower().endswith('.gz') else '.txt'
                payload=file.file.read(100*1024**2+1)
            finally:
                file.file.close()
            if not payload or len(payload)>100*1024**2:
                raise ValueError('上传文件为空或超过100 MiB')
            if dataset_id=='pancan':
                raise ValueError('PANCAN禁止上传替代数据，请复用固定640例开发集')
        return start(request,{'kind':'import','dataset_id':dataset_id,'download':download},payload,suffix)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc

@router.get('/datasets/{dataset_id}',response_model=DatasetInfo)
def dataset(request:Request,dataset_id:str):
    try:
        return request.app.state.datasets.info(dataset_id)
    except ValueError as exc:
        raise HTTPException(404,str(exc)) from exc

@router.get('/datasets/{dataset_id}/summary',response_model=DatasetInfo)
def dataset_summary(request:Request,dataset_id:str):
    try:
        return request.app.state.datasets.summary(dataset_id)
    except (ValueError,FileNotFoundError) as exc:
        raise HTTPException(409,str(exc)) from exc

@router.get('/algorithms',response_model=Items)
def algorithms():
    return {'items':[{'id':key,'name':name} for key,name in ALGORITHMS.items()]}

@router.get('/features/methods')
def methods():
    return {'items':[{'id':key,'name':name} for key,name in METHODS.items()],'k_values':[20,50,100,300,500,1000]}

@router.post('/experiments',response_model=Snapshot,status_code=202)
def experiment(request:Request,config:ExperimentConfig):
    meta=request.app.state.datasets.info(config.dataset_id)
    if meta['status']!='ready':
        raise HTTPException(409,'数据集待导入；无法开始训练')
    if min(meta['class_counts'].values())<config.folds:
        raise HTTPException(422,'最小类别样本数小于CV折数')
    if config.selection!='none' and config.k>meta['features']-meta['quality']['constant_features']:
        raise HTTPException(422,'K超过数据集非恒定特征数；训练折将再次核验')
    return start(request,{'kind':'experiment','dataset_id':config.dataset_id,'dataset_version':meta['version'],'experiment_config':config.model_dump()})

@router.get('/experiments',response_model=Items)
def experiments(request:Request,search:str=Query('',max_length=80),status:str|None=None,dataset_id:str|None=None,
                sort_by:Literal['created_at','elapsed_seconds']='created_at',descending:bool=True):
    items=request.app.state.platform_jobs.list()
    items=[r for r in items if r.get('kind')=='experiment' and (not status or r['status']==status) and (not dataset_id or r['dataset_id']==dataset_id)
           and search.lower() in (r['task_id']+r['dataset_id']+json.dumps(r['experiment_config'])).lower()]
    return {'items':sorted(items,key=lambda r:r.get(sort_by,0),reverse=descending)}

@router.get('/experiments/{task_id}',response_model=Snapshot)
def experiment_detail(request:Request,task_id:str):
    return state(request,task_id)

@router.post('/experiments/{task_id}/cancel',response_model=Snapshot)
def cancel(request:Request,task_id:str):
    local_mutation(request)
    state(request,task_id)
    try:
        return request.app.state.platform_jobs.cancel(task_id)
    except TaskConflict as exc:
        raise HTTPException(409,str(exc)) from exc

@router.get('/experiments/{task_id}/results',response_model=ResultSchema,response_model_exclude_none=True)
def results(request:Request,task_id:str):
    return detail(request,task_id)

@router.get('/experiments/{task_id}/events')
async def events(request:Request,task_id:str):
    state(request,task_id)
    async def stream():
        revision=-1
        while not await request.is_disconnected():
            current=state(request,task_id)
            if current['revision']!=revision:
                revision=current['revision']
                yield f'id: {revision}\nevent: snapshot\ndata: {json.dumps(current,ensure_ascii=False)}\n\n'
            else:
                yield ': keepalive\n\n'
            if current['status'] in TERMINAL:
                break
            await asyncio.sleep(.5)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@router.get('/experiments/{task_id}/logs')
def logs(request:Request,task_id:str):
    state(request,task_id)
    path=request.app.state.platform_jobs.directory(task_id)/'events.jsonl'
    return {'items':[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()[-200:]] if path.exists() else []}

@router.get('/experiments/{task_id}/export')
def export(request:Request,task_id:str,format:Literal['csv','json']='json'):
    task=state(request,task_id)
    if format=='json':
        content=json.dumps({'task':task,'results':detail(request,task_id) if task['status']=='completed' else None},ensure_ascii=False,indent=2)
    else:
        content='\ufeff'+pd.DataFrame(task.get('folds',[])).to_csv(index=False)
    return Response(content,media_type='text/csv' if format=='csv' else 'application/json',headers={'Content-Disposition':f'attachment; filename="experiment_{task_id}.{format}"'})

@router.get('/models',response_model=Items)
def models(request:Request,dataset_id:str|None=None):
    return {'items':Models(request.app.state.platform_jobs.project).list(dataset_id)}

@router.get('/models/{model_id}',response_model=ModelInfo)
def model(request:Request,model_id:str):
    try:
        return Models(request.app.state.platform_jobs.project).get(model_id)
    except (ValueError,OSError) as exc:
        raise HTTPException(404,str(exc)) from exc

@router.get('/comparison',response_model=Items)
def comparison(request:Request,task_ids:str=Query(...,max_length=600)):
    ids=task_ids.split(',')
    if not 1<=len(ids)<=12:
        raise HTTPException(422,'最多比较12个任务')
    return {'items':[{'task_id':key,**detail(request,key)} for key in ids]}

@router.get('/features/analysis',response_model=FeatureSchema)
def features(request:Request,task_id:str,dataset_id:str|None=None):
    output=detail(request,task_id)
    if dataset_id and dataset_id!=output.get('dataset_id'):
        raise HTTPException(422,'实验与所选数据集不一致')
    if 'results' not in output:
        raise HTTPException(422,'所选任务不是分类实验')
    items=output['results']
    sets={r['algorithm']:{f['feature'] for f in r['selection_frequency']} for r in items}
    from itertools import combinations
    overlap=[{'left':a,'right':b,'intersection':len(sets[a]&sets[b]),'jaccard':len(sets[a]&sets[b])/len(sets[a]|sets[b])} for a,b in combinations(sets,2)]
    return {'dataset_id':output['dataset_id'],'items':[{'algorithm':r['algorithm'],'ranking':r['ranking'],'frequency':r['selection_frequency'],'jaccard_mean':r['jaccard_mean']} for r in items],
            'overlap':overlap,'scope':'排名来自全部允许开发样本最终拟合，仅用于探索；频率与Jaccard来自CV训练折'}
