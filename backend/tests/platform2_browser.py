"""Real browser QA against local Vite/FastAPI. Run after platform2_live_smoke."""
import json
import time
from pathlib import Path
import pandas as pd
from playwright.sync_api import sync_playwright
from backend.app.platform2.data import Datasets

ROOT=Path(__file__).resolve().parents[2]
BASE='http://127.0.0.1:5174'
EDGE=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

def run():
    errors=[]
    report={'pages':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=EDGE)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        for route,title in [('/','生物信息学交互式实验平台'),('/datasets','数据集中心'),('/lab','交互式模型实验室'),('/comparison','模型对比'),('/features','特征分析'),('/predict','单样本预测'),('/experiments','实验历史'),('/research','基于 RNA-Seq 的高维基因表达'),('/dataset','RNA-Seq 数据探索'),('/models','模型性能对比'),('/fusion','特征融合与消融'),('/legacy/lab','交互式模型实验室')]:
            page.goto(BASE+route,wait_until='networkidle',timeout=60000)
            page.locator('h1').first.wait_for()
            assert title in page.locator('h1').first.inner_text(),(route,page.locator('h1').first.inner_text())
            report['pages'].append(route)
        page.goto(BASE+'/datasets',wait_until='networkidle')
        assert page.get_by_text('已就绪',exact=True).count()==4
        page.get_by_role('button',name='查看详情',exact=True).nth(2).click()
        page.get_by_text('individual id',exact=False).first.wait_for()
        page.locator('.arco-modal canvas').first.wait_for()
        report['dataset_details_and_heatmap']=True
        page.locator('.arco-modal-close-icon').click()
        page.goto(BASE+'/lab',wait_until='networkidle')
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_lab.png'),full_page=True)
        # Inspect controls after React and Arco are rendered, then select the real dataset and pipeline.
        page.get_by_label('实验数据集',exact=True).click()
        page.get_by_role('option',name='GSE45827 乳腺癌亚型',exact=True).click()
        page.get_by_label('特征选择',exact=True).click()
        page.get_by_role('option',name='Variance Top-K',exact=True).click()
        page.get_by_label('特征数量 K',exact=True).click()
        page.get_by_role('option',name='20',exact=True).click()
        page.get_by_label('CV 折数',exact=True).fill('3')
        with page.expect_response(lambda r:r.url.endswith('/api/v1/experiments') and r.request.method=='POST') as created:
            page.get_by_role('button',name='开始实验',exact=True).click()
        response=created.value
        assert response.status==202,response.text()
        task=response.json()['task_id']
        page.wait_for_url('**/monitor/'+task)
        page.get_by_role('heading',name='实时训练监控',exact=True).wait_for()
        page.get_by_role('heading',name='实验已完成',exact=True).wait_for(timeout=180000)
        page.locator('canvas').first.wait_for()
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_monitor.png'),full_page=True)
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('heading',name='实验已完成',exact=True).wait_for(timeout=30000)
        report['browser_created_task_id']=task
        report['sse_chart_and_refresh_recovery']=True
        page.goto(BASE+'/comparison?ids='+task,wait_until='networkidle')
        page.locator('canvas').first.wait_for()
        page.get_by_text('CV 平均表现',exact=True).wait_for()
        report['comparison_chart']=True
        page.goto(BASE+'/features',wait_until='networkidle')
        page.get_by_label('选择数据集',exact=True).click()
        page.get_by_role('option',name='GSE45827 乳腺癌亚型',exact=True).click()
        page.get_by_label('选择特征实验',exact=True).click()
        page.get_by_role('option').first.click()
        page.get_by_text('平均 Jaccard',exact=True).wait_for()
        page.locator('canvas').first.wait_for()
        report['feature_results']=True
        page.goto(BASE+'/predict',wait_until='networkidle')
        page.get_by_label('选择数据集',exact=True).click()
        page.get_by_role('option',name='GSE45827 乳腺癌亚型',exact=True).click()
        page.get_by_label('预测模型',exact=True).click()
        page.get_by_role('option').first.click()
        data=Datasets().load('gse45827')
        frame=pd.DataFrame([data.X[0]],columns=data.feature_names)
        frame.insert(0,'sample_id',data.sample_ids[0])
        page.locator('input[type=file]').set_input_files({'name':'measured_sample.csv','mimeType':'text/csv','buffer':frame.to_csv(index=False).encode()})
        with page.expect_response(lambda r:r.url.endswith('/api/v1/predict')) as predicted:
            page.get_by_role('button',name='执行预测',exact=True).click()
        assert predicted.value.status==200,predicted.value.text()
        page.locator('.platform-prediction > strong').wait_for()
        report['csv_prediction']=predicted.value.json()['data']
        page.get_by_label('切换深色主题',exact=True).click()
        assert page.locator('body').get_attribute('arco-theme')=='dark'
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_dark.png'),full_page=True)
        page.reload(wait_until='networkidle')
        assert page.locator('body').get_attribute('arco-theme')=='dark'
        page.get_by_label('切换深色主题',exact=True).click()
        report['theme_persistence']=True
        page.goto(BASE+'/',wait_until='networkidle')
        page.screenshot(path=str(ROOT/'reports/genescope2_browser_overview.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_label('打开导航',exact=True).click()
        page.locator('.arco-drawer-content').wait_for()
        report['mobile_navigation']=True
        browser.close()
    report['page_errors']=errors
    assert not errors,errors
    (ROOT/'reports/genescope2_browser_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    run()
