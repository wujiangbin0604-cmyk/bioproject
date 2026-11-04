"""UI acceptance with real local APIs; screenshots are runtime output, never reference art.

Run with the same Python 3.14 environment as the frozen models and local servers on 8001/5174.
--routes captures every route without starting new computation; --flows runs the real experiment.
"""
import argparse
import json
import time
from pathlib import Path
import pandas as pd
from playwright.sync_api import sync_playwright
from backend.app.platform2.data import Datasets

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports' / 'frontend-refresh'
BASE = 'http://127.0.0.1:5174'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def run(flows=False, flows_only=False):
    OUT.mkdir(parents=True, exist_ok=True)
    report, errors = {'routes': [], 'checks': []}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=EDGE)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_default_timeout(15000)

        def visit(route):
            page.goto(BASE + route, wait_until='networkidle', timeout=60000)
            page.locator('h1').first.wait_for()

        def shot(name):
            page.screenshot(path=str(OUT / (name + '.png')), full_page=True, animations='disabled')

        def no_overflow(label):
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), label

        tasks = page.request.get(BASE + '/api/v1/experiments?status=completed').json()['items']
        saved = next(t for t in tasks if t['dataset_id'] == 'gse45827')
        saved_id = saved['task_id']
        routes = [('/', '欢迎使用 GeneScope 2.0', 'overview'), ('/datasets', '数据集中心', 'datasets'),
                  ('/lab', '模型实验室', 'lab'), ('/monitor', '实时任务中心', 'tasks'),
                  ('/monitor/' + saved_id, '实时训练监控', 'monitor'),
                  ('/comparison?ids=' + saved_id, '模型对比', 'comparison'),
                  ('/features?dataset=gse45827&task=' + saved_id, '特征分析', 'features'),
                  ('/predict', '单样本预测', 'prediction'), ('/experiments', '实验历史', 'history'),
                  ('/settings', '系统设置', 'settings'), ('/research', '基于 RNA-Seq', 'research'),
                  ('/dataset', 'RNA-Seq 数据探索', 'research-dataset'),
                  ('/research/features', '特征选择', 'research-features'), ('/models', '模型性能对比', 'research-models'),
                  ('/fusion', '特征融合', 'research-fusion'), ('/legacy/lab', '交互式模型实验室', 'legacy-lab'),
                  ('/legacy/predict', '单样本', 'legacy-prediction'), ('/about', '关于', 'about')]
        for route, title, name in ([] if flows_only else routes):
            visit(route)
            assert title in page.locator('h1').first.inner_text(), (route, page.locator('h1').first.inner_text())
            no_overflow(route)
            if not name.startswith(('research', 'legacy')) and name != 'about':
                shot('desktop-' + name)
            report['routes'].append(route)
            print('route OK', name, flush=True)

        visit('/datasets')
        page.get_by_role('button', name='收藏 GSE45827 乳腺癌亚型', exact=True).click()
        page.reload(wait_until='networkidle')
        assert page.get_by_role('button', name='取消收藏 GSE45827 乳腺癌亚型', exact=True).count() == 1
        page.get_by_label('搜索数据集', exact=True).fill('GSE45827')
        page.wait_for_timeout(350)
        assert page.locator('.interactive-dataset-card').count() == 1
        page.get_by_role('button', name='查看详情', exact=True).click()
        page.locator('.dataset-detail-drawer canvas').first.wait_for()
        shot('dataset-drawer')
        page.locator('.arco-drawer-close-icon').click()
        page.get_by_label('表格视图', exact=True).click()
        assert page.locator('.arco-table').count() == 1
        report['checks'].append('dataset search, favorites persistence, drawer heatmap, table view')

        visit('/')
        page.keyboard.press('Control+k')
        page.get_by_label('搜索平台内容', exact=True).fill('GSE45827')
        page.locator('.search-results button').first.click()
        assert '/datasets' in page.url
        report['checks'].append('keyboard global search navigates to actual dataset')

        visit('/')
        before = page.locator('.chart-resize-container canvas').first.bounding_box()['width']
        page.get_by_label('收起侧边栏', exact=True).click()
        page.wait_for_timeout(450)
        after = page.locator('.chart-resize-container canvas').first.bounding_box()['width']
        assert after > before, (before, after)
        page.reload(wait_until='networkidle')
        assert 'sidebar-collapsed' in page.locator('.bio-shell').get_attribute('class')
        page.get_by_label('展开侧边栏', exact=True).click()
        report['checks'].append('sidebar persistence and ResizeObserver canvas resize')

        visit('/settings')
        page.get_by_label('启用交互动效', exact=True).click()
        visit('/')
        assert page.locator('html').get_attribute('data-motion') == 'reduced'
        assert page.locator('.dna-hero').get_attribute('data-active') == 'false'
        assert page.locator('.page-enter').evaluate("el=>getComputedStyle(el).animationName") == 'none'
        visit('/settings')
        page.get_by_role('button', name='恢复默认偏好', exact=True).click()
        page.emulate_media(reduced_motion='reduce')
        visit('/')
        assert page.locator('.dna-hero').get_attribute('data-active') == 'false'
        page.emulate_media(reduced_motion='no-preference')
        report['checks'].append('stored motion preference and OS reduced-motion respected')

        for width, height, name in ([] if flows_only else [(1920,1080,'wide'), (1280,800,'laptop'), (1024,900,'tablet'), (390,844,'mobile')]):
            page.set_viewport_size({'width': width, 'height': height})
            for route, _, screen in routes[:10]:
                visit(route)
                no_overflow((name, route))
                if name != 'wide' or screen == 'overview':
                    shot(name + '-' + screen)
            if name == 'mobile':
                page.get_by_label('打开导航', exact=True).click()
                page.locator('.bio-nav-drawer').wait_for()
                page.locator('.bio-nav-drawer').get_by_text('数据集中心', exact=True).click()
                page.wait_for_url('**/datasets')
                report['checks'].append('mobile drawer keyboard-accessible navigation')
        page.set_viewport_size({'width':1440,'height':1000})

        if flows:
            posts = []
            page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' and request.url.endswith('/api/v1/experiments') else None)
            visit('/lab?dataset=gse45827')
            page.get_by_role('button', name='重置配置', exact=True).click()
            page.locator('.lab-dataset-option').filter(has_text='GSE45827').click()
            page.get_by_role('button', name='下一步', exact=False).click()
            page.get_by_label('特征数量 K', exact=True).fill('20')
            page.get_by_label('特征数量 K', exact=True).press('Tab')
            assert not posts, 'K editing must not submit a task'
            page.reload(wait_until='networkidle')
            page.get_by_role('button', name='下一步', exact=False).click()
            assert page.get_by_label('特征数量 K', exact=True).input_value() == '20'
            shot('lab-model-selection')
            page.get_by_role('button', name='下一步', exact=False).click()
            page.get_by_label('交叉验证折数', exact=True).fill('3')
            page.get_by_label('交叉验证折数', exact=True).press('Tab')
            page.get_by_role('button', name='下一步', exact=False).click()
            assert not posts
            with page.expect_response(lambda r: r.url.endswith('/api/v1/experiments') and r.request.method == 'POST') as created:
                page.get_by_role('button', name='开始实验', exact=False).click()
            assert created.value.status == 202, created.value.text()
            task = created.value.json()['task_id']
            report['created_task_id'] = task
            page.wait_for_url('**/monitor/' + task)
            page.get_by_role('heading', name='最终汇总', exact=False).wait_for(timeout=180000)
            assert len(posts) == 1
            shot('real-completed-experiment')
            page.reload(wait_until='networkidle')
            page.get_by_role('heading', name='最终汇总', exact=False).wait_for()
            page.get_by_text('计算耗时', exact=True).click()
            page.get_by_label('筛选任务日志', exact=True).fill('完成')
            report['checks'].append('persisted four-step config, single real submission, SSE completion, refresh recovery, real folds and logs')

            visit('/comparison?ids=' + task)
            page.get_by_text('CV耗时', exact=True).click()
            page.locator('canvas').first.wait_for()
            visit('/features?dataset=gse45827&task=' + task)
            page.get_by_role('button', name='切换视图', exact=True).click()
            page.locator('.heatmap-explorer canvas').wait_for()
            report['checks'].append('comparison metric tabs and expression heatmap transpose')

            visit('/predict?dataset=gse45827')
            data = Datasets().load('gse45827')
            frame = pd.DataFrame([data.X[0]], columns=data.feature_names)
            frame.insert(0, 'sample_id', data.sample_ids[0])
            page.locator('input[type=file]').set_input_files({'name':'measured_sample.csv','mimeType':'text/csv','buffer':frame.to_csv(index=False).encode()})
            page.get_by_role('button', name='下一步', exact=False).click()
            page.get_by_label('预测模型', exact=True).click()
            page.get_by_role('option').first.click()
            page.get_by_role('button', name='开始预测', exact=False).wait_for(state='visible')
            with page.expect_response(lambda r:r.url.endswith('/api/v1/predict')) as predicted:
                page.get_by_role('button', name='开始预测', exact=False).click()
            assert predicted.value.status == 200, predicted.value.text()
            page.get_by_role('heading', name='预测已完成', exact=False).wait_for()
            report['prediction'] = predicted.value.json()['data']
            shot('prediction-real-result')
            page.get_by_role('button', name='移除样本文件', exact=True).click()
            page.locator('input[type=file]').set_input_files({'name':'bad.csv','mimeType':'text/csv','buffer':b'A,A\n1,2\n'})
            page.get_by_text('CSV存在重复特征列', exact=True).wait_for()
            assert page.get_by_role('button', name='下一步', exact=False).is_disabled()
            report['checks'].append('real measured single-sample prediction, true upload progress, invalid CSV blocked')

            # A real cancellable task also verifies that route changes close the SSE subscription.
            config = {**saved['experiment_config'], 'algorithms':['random_forest'], 'folds':5,'repeats':2,'n_estimators':100}
            response = page.request.post(BASE+'/api/v1/experiments', data=config)
            assert response.status == 202, response.text()
            cancel_id = response.json()['task_id']
            visit('/monitor/' + cancel_id)
            page.get_by_role('button', name='取消任务', exact=True).click()
            page.get_by_role('button', name='确定', exact=True).click()
            page.locator('.monitor-progress-card .status-cancelled').wait_for(timeout=30000)
            assert page.request.get(BASE+'/api/v1/experiments/'+cancel_id).json()['status']=='cancelled'
            report['cancelled_task_id'] = cancel_id
            report['checks'].append('real worker cancellation and terminal timeline')

        report['page_errors'] = errors
        assert not errors, errors
        browser.close()
    name = 'flows' if flows else 'routes'
    (OUT/(name+'-acceptance.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--flows',action='store_true')
    parser.add_argument('--routes',action='store_true')
    parser.add_argument('--flows-only',action='store_true')
    args=parser.parse_args()
    run(args.flows or args.flows_only, args.flows_only)
