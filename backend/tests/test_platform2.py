"""Protocol/security unit tests plus real subprocess training on sklearn's measured iris data.
Test fixtures never become catalog data or reported bioinformatics performance.
"""
import io
import json
import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sklearn.datasets import load_iris
from backend.app.main import create_app
from backend.app.platform2.data import Datasets, Dataset, DEFINITIONS, digest
from backend.app.platform2.engine import ExperimentConfig, FoldSelector, pipeline, splits
from backend.app.platform2.jobs import Jobs
from backend.app.platform2.models import Models
from backend.app.lab_config import atomic_json

def measured_fixture(root):
    original=load_iris()
    # Four measured features, each represented at five scales solely to exercise K=20 plumbing.
    X=np.hstack([original.data*(1+i*.1) for i in range(5)])
    spec=Datasets(root).definition('gse4290')
    Datasets(root).save(spec,X,[str(c) for c in original.target],[f'iris_{i}' for i in range(150)],
                        [f'measured_{i}' for i in range(20)],None,{'source_sha256':'iris-measured-test-fixture','source':'sklearn iris; test-only, not GEO'},[])

def wait(jobs,key,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=jobs.get(key)
        if state['status'] in {'completed','failed','cancelled'}:
            # Allow resource monitor to release the shared concurrency lock.
            while key in jobs.processes and time.monotonic()<deadline:
                time.sleep(.1)
            return state
        time.sleep(.15)
    raise AssertionError('worker timed out')

@pytest.mark.parametrize('kwargs',[{'algorithms':['evil']},{'k':21},{'folds':1},{'seed':-1},{'c':float('nan')},{'c':1000},{'repeats':9},{'file_path':'secret'},{'algorithms':['linear_svc','linear_svc']}])
def test_config_rejects_invalid(kwargs):
    with pytest.raises(ValidationError):
        ExperimentConfig(dataset_id='gse4290',**kwargs)

@pytest.mark.parametrize('algorithm',['linear_svc','logistic_regression','random_forest','rbf_svm'])
@pytest.mark.parametrize('method',['none','anova','variance','coefficient'])
def test_all_real_classifier_selector_combinations(algorithm,method):
    iris=load_iris()
    X=np.hstack([iris.data]*5)
    config=ExperimentConfig(dataset_id='gse4290',algorithms=[algorithm],selection=method,k=20,n_estimators=10)
    model=pipeline(config,algorithm).fit(X,iris.target)
    assert len(model.predict(X[:2]))==2
    if method!='none':
        assert model.named_steps['select'].get_support().sum()==20
        assert model.named_steps['select'].n_samples_seen_==150
    if 'scale' in model.named_steps:
        assert model.named_steps['scale'].n_samples_seen_==150

def test_k_rechecked_inside_training_fold():
    X=np.ones((10,25)); X[:,0]=np.arange(10)
    with pytest.raises(ValueError,match='有效特征'):
        FoldSelector(k=20).fit(X,np.arange(10)%2)

def test_group_protocol_and_repeated_splits_are_deterministic():
    y=np.tile(np.array(['a','b']),20)
    groups=np.repeat(np.arange(20),2)
    d=Dataset(np.arange(800).reshape(40,20),y,[str(i) for i in range(40)],[],groups,{},'group')
    cfg=ExperimentConfig(dataset_id='gse44076',folds=5,repeats=2,k=20)
    first=splits(d,cfg); second=splits(d,cfg)
    assert len(first)==10
    for a,b in zip(first,second):
        assert np.array_equal(a[2],b[2])
        assert not set(groups[a[2]])&set(groups[a[3]])

def test_import_requires_official_labels_and_group_metadata(tmp_path):
    p=tmp_path/'invalid.txt'
    p.write_text('!Series_geo_accession\t"GSE44076"\n!Sample_geo_accession\t"GSM1"\t"GSM2"\n!Sample_platform_id\t"GPL13667"\t"GPL13667"\n!Sample_title\t"x"\t"y"\n!Sample_characteristics_ch1\t"sample type: Tumor"\t"sample type: Normal"\n!series_matrix_table_begin\n"ID_REF"\t"GSM1"\t"GSM2"\n"probe"\t1\t2\n!series_matrix_table_end\n',encoding='utf-8')
    with pytest.raises(ValueError,match='分组'):
        Datasets(tmp_path).import_geo('gse44076',p)
    assert Datasets(tmp_path).info('gse44076')['status']=='pending'

def test_api_empty_states_and_security(tmp_path):
    with TestClient(create_app(tmp_path),client=('127.0.0.1',1234)) as client:
        assert len(client.get('/api/v1/datasets').json()['items'])==4
        assert client.post('/api/v1/experiments',json={'dataset_id':'gse4290'}).status_code==409
        assert client.post('/api/v1/experiments',json={'dataset_id':'gse4290','code':'print(1)'}).status_code==422
        assert client.get('/api/v1/experiments/not-an-id').status_code==404
        assert client.get('/api/v1/models/../../config.py').status_code==404
        assert client.post('/api/v1/datasets/import',data={'dataset_id':'../outside'}).status_code==422
        assert client.post('/api/v1/datasets/import',data={'dataset_id':'gse4290'},headers={'origin':'https://evil.test'}).status_code==403
        assert client.post('/api/v1/datasets/import',data={'dataset_id':'gse4290'},files={'file':('evil.joblib',b'pickle')}).status_code==422
        assert client.post('/api/v1/predict',data={'dataset_id':'gse4290'},files={'file':('x.csv',b'a\n1')}).status_code==422

def test_task_training_sse_registry_predict_and_restart(tmp_path):
    measured_fixture(tmp_path)
    config={'dataset_id':'gse4290','k':20,'folds':3,'algorithms':['linear_svc','logistic_regression','random_forest','rbf_svm'],'n_estimators':10}
    with TestClient(create_app(tmp_path),client=('127.0.0.1',1234)) as client:
        task=client.post('/api/v1/experiments',json=config)
        assert task.status_code==202,task.text
        key=task.json()['task_id']; manager=client.app.state.platform_jobs
        assert client.post('/api/v1/experiments',json=config).status_code==409
        done=wait(manager,key)
        assert done['status']=='completed',done
        assert done['completed_folds']==12 and done['progress']==100
        stream=client.get(f'/api/v1/experiments/{key}/events')
        assert 'event: snapshot' in stream.text and 'completed' in stream.text
        results=client.get(f'/api/v1/experiments/{key}/results').json()
        assert len(results['results'])==4
        model=client.get('/api/v1/models?dataset_id=gse4290').json()['items'][0]
        dataset=Datasets(tmp_path).load('gse4290')
        sample=','.join(['sample_id',*dataset.feature_names])+'\n'+','.join(['test',*map(str,dataset.X[0])])
        response=client.post('/api/v1/predict',data={'dataset_id':'gse4290','model_id':model['model_id']},files={'file':('sample.csv',sample.encode())})
        assert response.status_code==200,response.text
        assert response.json()['data']['predicted_class'] in {'0','1','2'}
        assert client.post('/api/v1/predict',data={'dataset_id':'gse45827','model_id':model['model_id']},files={'file':('sample.csv',sample.encode())}).status_code==422
        assert client.get(f'/api/v1/experiments/{key}/export?format=csv').status_code==200
        assert client.get(f'/api/v1/features/analysis?task_id={key}&dataset_id=gse45827').status_code==422
        assert client.get(f'/api/v1/comparison?task_ids={key}').status_code==200
    with TestClient(create_app(tmp_path),client=('127.0.0.1',1234)) as restarted:
        assert restarted.get(f'/api/v1/experiments/{key}').json()['status']=='completed'
        assert len(restarted.get('/api/v1/models').json()['items'])==4

def test_cancel_stops_process_and_failed_import_can_retry(tmp_path):
    measured_fixture(tmp_path)
    jobs=Jobs(tmp_path)
    try:
        config=ExperimentConfig(dataset_id='gse4290',selection='none',folds=10,repeats=5,n_estimators=300,algorithms=['random_forest'])
        task=jobs.start({'kind':'experiment','dataset_id':'gse4290','dataset_version':Datasets(tmp_path).info('gse4290')['version'],'experiment_config':config.model_dump()})
        process=jobs.processes[task['task_id']]
        assert jobs.cancel(task['task_id'])['status']=='cancelled'
        assert process.poll() is not None
        wait(jobs,task['task_id'])
        bad=jobs.start({'kind':'import','dataset_id':'gse45827','download':False})
        failed=wait(jobs,bad['task_id'])
        assert failed['status']=='failed' and failed['error']
        assert Datasets(tmp_path).info('gse45827')['status']=='pending'
    finally:
        jobs.shutdown()

def test_model_tamper_rejected_before_joblib(tmp_path,monkeypatch):
    measured_fixture(tmp_path)
    # An unregistered directory must never be deserialized.
    key='b'*32; folder=tmp_path/'model_registry'/key
    folder.mkdir(parents=True); (folder/'pipeline.joblib').write_bytes(b'evil')
    atomic_json(folder/'metadata.json',{'source_experiment_id':'c'*32,'model_id':key,'artifact_sha256':'wrong'})
    called=[]
    monkeypatch.setattr('joblib.load',lambda *_:called.append(True))
    with pytest.raises((ValueError,OSError)):
        Models(tmp_path).predict(key,'gse4290',b'x\n1')
    assert not called

def test_atomic_state_replace_retries_windows_sharing_violation(tmp_path,monkeypatch):
    from backend.app import lab_config
    original=lab_config.os.replace
    calls=[]
    def briefly_locked(source,target):
        calls.append(True)
        if len(calls)<3:
            raise PermissionError('transient Windows sharing violation')
        return original(source,target)
    monkeypatch.setattr(lab_config.os,'replace',briefly_locked)
    atomic_json(tmp_path/'state.json',{'status':'running'})
    assert len(calls)==3 and json.loads((tmp_path/'state.json').read_text())['status']=='running'

def test_measured_geo_local_import_retry_and_isolation(tmp_path):
    from backend.app.platform2.data import PROJECT
    original=PROJECT/'datasets/gse4290/raw/GSE4290_series_matrix.txt.gz'
    if not original.exists():
        pytest.skip('Official local GEO matrix is not available in this checkout')
    datasets=Datasets(tmp_path)
    invalid=tmp_path/'invalid.txt'
    invalid.write_text('not a matrix',encoding='utf-8')
    with pytest.raises(ValueError):
        datasets.import_geo('gse4290',invalid)
    info=datasets.import_geo('gse4290',original)
    assert info['status']=='ready' and info['samples']==176 and info['quality']['excluded_count']==4
    assert datasets.info('gse45827')['status']=='pending'
    data=datasets.load('gse4290')
    assert data.metadata['feature_namespace']=='Affymetrix_probe_id'
    assert data.X.shape==(176,54613)
