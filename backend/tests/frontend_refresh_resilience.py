"""Real UI resilience: SSE transport failures, cleanup, dataset switching and network error states."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
BASE='http://127.0.0.1:5174'
EDGE=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def run():
    report={'checks':[]}; errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=EDGE)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        context.add_init_script("""window.__streams=[]; const NativeEventSource=window.EventSource;
        window.EventSource=class extends NativeEventSource { constructor(...args){super(...args);window.__streams.push(this);} };
        """)
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE+'/lab',wait_until='networkidle')
        tasks=page.request.get(BASE+'/api/v1/experiments?status=completed&dataset_id=gse45827').json()['items']
        config={**tasks[0]['experiment_config'],'selection':'none','algorithms':['random_forest'],'folds':10,'repeats':2,'n_estimators':300}
        response=page.request.post(BASE+'/api/v1/experiments',data=config)
        assert response.status==202,response.text()
        task=response.json()['task_id']; report['transport_test_task']=task
        detail=BASE+'/api/v1/experiments/'+task
        attempts=[]; gets=[]
        def transport(route):
            attempts.append(1)
            if len(attempts)<=2: route.abort('connectionreset')
            else: route.continue_()
        page.route('**/api/v1/experiments/'+task+'/events',transport)
        page.on('request',lambda r: gets.append(r.url) if r.url==detail and r.method=='GET' else None)
        try:
            page.goto(BASE+'/monitor/'+task,wait_until='domcontentloaded')
            page.get_by_text('实时连接暂时中断，正在重连并查询任务状态',exact=True).wait_for(timeout=20000)
            page.wait_for_function('window.__streams.some(s=>s.readyState===1)',timeout=25000)
            assert len(attempts)>=3,len(attempts)
            assert len(gets)>=2,len(gets)
            page.get_by_text('实时事件已连接',exact=True).wait_for()
            report['checks'].append('two real SSE transport failures, fallback GET and automatic reconnect')
            page.get_by_text('系统设置',exact=True).first.click()
            page.wait_for_url('**/settings')
            assert page.evaluate('window.__streams.every(s=>s.readyState===2)')
            count=len(gets)
            page.wait_for_timeout(6000)
            assert len(gets)==count,'task polling leaked after route change'
            report['checks'].append('route cleanup closes EventSource and stops fallback polling')
        finally:
            page.request.post(detail+'/cancel')
        page.goto(BASE+'/features?dataset=pancan',wait_until='networkidle')
        page.get_by_label('选择数据集',exact=True).click()
        page.get_by_role('option',name='GSE45827 乳腺癌亚型',exact=True).click()
        page.locator('.feature-score').first.wait_for()
        assert 'gse45827' in page.request.get(BASE+'/api/v1/experiments/'+tasks[0]['task_id']+'/results').json()['dataset_id']
        assert 'gene_' not in page.locator('.feature-analysis-grid').first.inner_text()
        report['checks'].append('dataset switch discards PANCAN ranking before showing GEO probe features')
        page.route('**/api/v1/datasets',lambda route:route.abort('connectionrefused'))
        page.goto(BASE+'/datasets',wait_until='networkidle')
        page.get_by_text('无法连接后端服务，请确认API已启动。',exact=True).wait_for()
        report['checks'].append('failed dataset API displays actionable error instead of invented records')
        report['page_errors']=errors
        assert not errors,errors
        browser.close()
    (ROOT/'reports/frontend-refresh/resilience-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':run()
