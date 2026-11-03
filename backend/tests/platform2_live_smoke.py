"""Explicit integration acceptance on the four real imported expression datasets."""
import io
import json
import time
from pathlib import Path
import httpx
import pandas as pd
from backend.app.platform2.data import Datasets

ROOT=Path(__file__).resolve().parents[2]
BASE='http://127.0.0.1:8001/api/v1'

def run():
    report={'source':'real_official_expression_data','datasets':[],'tasks':[]}
    with httpx.Client(base_url=BASE,trust_env=False,timeout=120) as client:
        def submit(config):
            response=client.post('/experiments',json=config)
            response.raise_for_status()
            key=response.json()['task_id']
            snapshots=[]
            with client.stream('GET',f'/experiments/{key}/events',timeout=600) as stream:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if line.startswith('data: '):
                        current=json.loads(line[6:])
                        snapshots.append({'status':current['status'],'completed_folds':current['completed_folds'],'progress':current['progress']})
                        if current['status'] in {'completed','failed','cancelled'}:
                            break
            assert current['status']=='completed',current
            result=client.get(f'/experiments/{key}/results').json()
            record={'task_id':key,'configuration':config,'sse_events':snapshots,
                    'models':[{'algorithm':r['algorithm'],'metrics':r['metrics'],'jaccard_mean':r['jaccard_mean'],'model_id':r['model_id']} for r in result['results']],
                    'split_sha256':result['split_sha256']}
            assert any(s['status']=='running' for s in snapshots),snapshots
            for suffix in ['export?format=csv','export?format=json','logs']:
                assert client.get(f'/experiments/{key}/{suffix}').status_code==200
            assert client.get(f'/features/analysis?task_id={key}').status_code==200
            report['tasks'].append(record)
            print('completed',key,config['dataset_id'],len(snapshots),'events',flush=True)
            # Wait for supervisor to release the single-runner process lock.
            time.sleep(.8)
            return key,result
        for key in ['pancan','gse4290','gse44076','gse45827']:
            meta=client.get(f'/datasets/{key}').json()
            report['datasets'].append({k:meta[k] for k in ['dataset_id','version','samples','features','class_counts','quality']})
            config={'dataset_id':key,'algorithms':['linear_svc','logistic_regression','random_forest','rbf_svm'],'selection':'anova','k':50,'folds':3,'n_estimators':30,'seed':42}
            task,result=submit(config)
            data=Datasets().load(key)
            sample=pd.DataFrame([data.X[0]],columns=data.feature_names)
            sample.insert(0,'sample_id',data.sample_ids[0])
            payload=sample.to_csv(index=False).encode()
            model=result['model_ids'][0]
            prediction=client.post('/predict',data={'dataset_id':key,'model_id':model},files={'file':('sample.csv',payload)})
            assert prediction.status_code==200,prediction.text
            report['tasks'][-1]['prediction']=prediction.json()['data']
            assert client.post('/predict',data={'dataset_id':'gse4290' if key=='pancan' else 'pancan','model_id':model},files={'file':('sample.csv',payload)}).status_code==422
        for selection in ['variance','coefficient','none']:
            submit({'dataset_id':'gse45827','algorithms':['linear_svc'],'selection':selection,'k':20,'folds':3,'seed':43})
        # A fresh long RF task must stop its actual operating-system process.
        cancel=client.post('/experiments',json={'dataset_id':'gse4290','algorithms':['random_forest'],'selection':'none','folds':5,'repeats':5,'n_estimators':300}).json()
        key=cancel['task_id']
        for _ in range(200):
            current=client.get(f'/experiments/{key}').json()
            if current['status']=='running':
                break
            time.sleep(.1)
        cancelled=client.post(f'/experiments/{key}/cancel')
        assert cancelled.status_code==200 and cancelled.json()['status']=='cancelled',cancelled.text
        report['cancelled_task_id']=key
        time.sleep(1)
        # Invalid raw upload should fail honestly, then release the runner for retries.
        failed=client.post('/datasets/import',data={'dataset_id':'gse4290'},files={'file':('bad.txt',b'not a matrix')}).json()
        fail_key=failed['task_id']
        for _ in range(300):
            current=client.get(f'/experiments/{fail_key}').json()
            if current['status'] in {'failed','completed'}:
                break
            time.sleep(.1)
        assert current['status']=='failed' and current['error']
        assert client.get('/datasets/gse4290').json()['status']=='ready'
        report['failed_import']={'task_id':fail_key,'error':current['error'],'existing_version_preserved':True}
        # Original frozen M1 path remains intact and outputs the same class as its original function.
        from deployment.predict import predict_single_sample
        data=Datasets().load('pancan')
        frame=pd.DataFrame([data.X[0]],columns=data.feature_names)
        frame.insert(0,'sample_id',data.sample_ids[0])
        original=predict_single_sample(frame)
        response=client.post('/predict',data={'dataset_id':'pancan','model_id':'frozen_m1'},files={'file':('sample.csv',frame.to_csv(index=False).encode())})
        assert response.status_code==200,response.text
        assert response.json()['data']['predicted_class']==original['predicted_class']
        report['frozen_m1_prediction']=response.json()['data']
    (ROOT/'reports/genescope2_live_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REAL DATA ACCEPTANCE PASSED',flush=True)

if __name__=='__main__':
    run()
