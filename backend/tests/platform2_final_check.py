"""Verify delivered PowerShell servers, persisted results, import recovery and final visuals."""
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]

def run():
    report={}
    with httpx.Client(base_url='http://127.0.0.1:8002/api/v1',trust_env=False,timeout=120) as client:
        tasks=client.get('/experiments').json()['items']
        completed=[t for t in tasks if t['status']=='completed']
        assert len(completed)>=8
        assert client.get('/health').json()['data']['model_available']
        model_count=len(client.get('/models').json()['items'])
        assert model_count>=20
        report.update(powershell_backend_started=True,restored_completed_tasks=len(completed),restored_models=model_count)
        with (ROOT/'datasets/gse4290/raw/GSE4290_series_matrix.txt.gz').open('rb') as stream:
            response=client.post('/datasets/import',data={'dataset_id':'gse4290'},files={'file':('GSE4290_series_matrix.txt.gz',stream,'application/gzip')})
        assert response.status_code==202,response.text
        key=response.json()['task_id']
        with client.stream('GET',f'/experiments/{key}/events',timeout=120) as stream:
            for line in stream.iter_lines():
                if line.startswith('data: '):
                    state=json.loads(line[6:])
                    if state['status'] in {'completed','failed'}:
                        break
        assert state['status']=='completed',state
        info=client.get('/datasets/gse4290').json()
        assert info['samples']==176 and info['download']['status']=='downloaded'
        report['official_multipart_import_recovery']={'task_id':key,'status':state['status'],'samples':info['samples']}
        report['powershell_frontend_proxy']=httpx.get('http://127.0.0.1:5175/api/v1/datasets',trust_env=False).status_code
        assert report['powershell_frontend_proxy']==200
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:5175/',wait_until='networkidle')
        page.locator('.metric-card').first.wait_for()
        cards=page.locator('.metric-grid .metric-card')
        assert cards.nth(0).bounding_box()['y']==cards.nth(1).bounding_box()['y']
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_overview.png'),full_page=True)
        page.goto('http://127.0.0.1:5175/lab',wait_until='networkidle')
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_lab.png'),full_page=True)
        page.get_by_label('切换深色主题',exact=True).click()
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_dark.png'),full_page=True)
        assert page.locator('body').get_attribute('arco-theme')=='dark'
        page.get_by_label('切换深色主题',exact=True).click()
        report['final_browser_errors']=errors
        assert not errors
        browser.close()
    (ROOT/'reports/genescope2_final_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    run()
