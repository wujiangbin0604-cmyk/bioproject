"""从干净本地运行包验证首次打开、原模型、离线导入和真实实验。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def run(client, matrix, port):
    client = Path(client).resolve()
    python = client / ('.venv-local/Scripts/python.exe' if os.name == 'nt' else '.venv-local/bin/python')
    env = {**os.environ, 'PYTHONPATH': '', 'PYTHONUTF8': '1'}
    report = {'client_version': (client/'VERSION').read_text().strip(), 'isolated_environment': True, 'checks': []}
    verified = subprocess.check_output([str(python), 'genescope.py', 'verify'], cwd=client, env=env)
    report['integrity'] = json.loads(verified)
    base = f'http://127.0.0.1:{port}'
    errors, external = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
        page = browser.new_page(viewport={'width':1440, 'height':900})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: external.append(request.url) if urlparse(request.url).scheme in {'http','https'} and urlparse(request.url).hostname not in {'127.0.0.1','localhost'} else None)
        page.goto(base, wait_until='networkidle')
        health = page.request.get(base+'/api/v1/health').json()['data']
        assert health['model_available'] is True
        datasets = page.request.get(base+'/api/v1/datasets').json()['items']
        assert all(item['status']=='pending' for item in datasets)
        assert page.request.get(base+'/api/v1/experiments').json()['items']==[]
        assert page.request.get(base+'/api/v1/models').json()['items']==[]
        report['initial_ready_datasets'] = 0
        report['initial_registered_models'] = 0
        page.screenshot(path=str(ROOT/'docs/screenshots/genescope2-first-open.png'), full_page=True, animations='disabled')
        report['checks'].append('fresh package has no hidden dataset/model cache; same-port API is usable')
        for route in ['/datasets','/lab','/predict','/monitor','/comparison','/features','/experiments','/settings']:
            page.goto(base+route, wait_until='networkidle')
            page.locator('h1').first.wait_for()
        page.reload(wait_until='networkidle')
        assert page.request.get(base+'/api/v1/does-not-exist').status==404
        assert page.request.get(base+'/assets/missing.js').status==404
        report['checks'].append('production assets and route refresh work without Vite or an online website')
        page.goto(base+'/predict', wait_until='networkidle')
        page.get_by_role('button', name='加载合成格式示例', exact=True).click()
        page.get_by_role('button', name='下一步', exact=False).click()
        with page.expect_response(lambda response: response.url.endswith('/api/v1/predict')) as predicted:
            page.get_by_role('button', name='开始预测', exact=False).click()
        assert predicted.value.status==200, predicted.value.text()
        assert predicted.value.json()['data']['sample_id']=='synthetic_format_example'
        report['checks'].append('trusted frozen M1 predicts the explicitly synthetic format example')
        subprocess.run([str(python), 'genescope.py', 'data', 'gse45827', '--file', str(Path(matrix).resolve())], cwd=client, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        info = page.request.get(base+'/api/v1/datasets/gse45827').json()
        assert info['status']=='ready' and info['samples']==130
        report['checks'].append('official matrix imported from a local file with no download dependency')
        page.goto(base+'/lab?dataset=gse45827', wait_until='networkidle')
        page.get_by_role('button', name='下一步', exact=False).click()
        page.get_by_label('特征数量 K', exact=True).fill('20')
        page.get_by_label('特征数量 K', exact=True).press('Tab')
        page.get_by_role('button', name='下一步', exact=False).click()
        page.get_by_label('交叉验证折数', exact=True).fill('3')
        page.get_by_label('交叉验证折数', exact=True).press('Tab')
        page.get_by_role('button', name='下一步', exact=False).click()
        with page.expect_response(lambda response: response.url.endswith('/api/v1/experiments') and response.request.method=='POST') as started:
            page.get_by_role('button', name='开始实验', exact=False).click()
        assert started.value.status==202, started.value.text()
        task = started.value.json()['task_id']
        page.wait_for_url('**/monitor/'+task)
        page.get_by_role('heading', name='最终汇总', exact=False).wait_for(timeout=180000)
        saved = page.request.get(base+'/api/v1/experiments/'+task).json()
        assert saved['status']=='completed' and len(saved['folds'])==3
        report['experiment_task_id'] = task
        report['checks'].append('independent local worker completes real 3-fold CV and registers its model')
        sample = subprocess.check_output([str(python), '-c', "from backend.app.platform2.data import Datasets; import pandas as pd; d=Datasets().load('gse45827'); f=pd.DataFrame([d.X[0]],columns=d.feature_names); f.insert(0,'sample_id',d.sample_ids[0]); print(f.to_csv(index=False),end='')"], cwd=client, env=env)
        page.goto(base+'/predict?dataset=gse45827', wait_until='networkidle')
        page.locator('input[type=file]').set_input_files({'name':'measured_sample.csv','mimeType':'text/csv','buffer':sample})
        page.get_by_role('button', name='下一步', exact=False).click()
        page.get_by_label('预测模型', exact=True).click()
        page.get_by_role('option').first.click()
        with page.expect_response(lambda response: response.url.endswith('/api/v1/predict')) as predicted:
            page.get_by_role('button', name='开始预测', exact=False).click()
        assert predicted.value.status==200, predicted.value.text()
        report['registered_model_prediction'] = predicted.value.json()['data']['predicted_class']
        report['checks'].append('new local registered model predicts a measured same-dataset sample')
        assert not external, external
        assert not errors, errors
        report['external_frontend_requests'] = external
        report['page_errors'] = errors
        browser.close()
    report_file = ROOT/'reports/local-client-acceptance.json'
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--client-dir', type=Path, required=True)
    parser.add_argument('--official-matrix', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8791)
    args=parser.parse_args()
    run(args.client_dir, args.official_matrix, args.port)
