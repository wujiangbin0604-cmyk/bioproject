"""Read-only dashboard acceptance against an existing local API; never creates training jobs."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(ROOT / 'backend' / '.vendor'))
from playwright.sync_api import sync_playwright, expect


def run(args):
    output = ROOT / 'reports' / 'research-dashboard'
    output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'page_errors': [], 'console_errors': [], 'layouts': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        context.add_init_script("localStorage.setItem('genescope-ui-preferences', JSON.stringify({theme:'light',motion:false,collapsed:false}));")
        page = context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        page.on('console', lambda message: report['console_errors'].append(message.text) if message.type == 'error' else None)
        page.goto(args.url, wait_until='networkidle')
        expect(page.get_by_role('heading', name='项目总览', exact=True)).to_be_visible()
        expect(page.get_by_text('系统运行正常', exact=True)).to_be_visible()
        expect(page.locator('.summary-card')).to_have_count(4)
        expect(page.locator('.research-workflow li')).to_have_count(6)
        page.locator('.research-dashboard canvas').first.wait_for()
        datasets = page.request.get(args.url + '/api/v1/datasets').json()['items']
        report['datasets'] = [{'id': d['dataset_id'], 'status': d['status'], 'samples': d.get('samples')} for d in datasets]
        report['checks'].append('live API, four summary cards, workflow, ECharts canvas and service status loaded')

        for width, height, name in [(1920,1080,'desktop-wide'), (1440,1000,'desktop'), (1024,900,'tablet'), (390,844,'mobile')]:
            page.set_viewport_size({'width':width, 'height':height})
            page.wait_for_timeout(250)
            metrics = page.evaluate('({body:document.body.scrollWidth, viewport:innerWidth, header:document.querySelector(".bio-topbar").scrollWidth})')
            assert metrics['body'] <= width + 1, (name, metrics)
            assert metrics['header'] <= width + 1, (name, metrics)
            report['layouts'].append({'name':name, **metrics})
            page.screenshot(path=str(output / (name + '.png')), full_page=True, animations='disabled')
        report['checks'].append('1920 / 1440 / 1024 / 390 layouts have no page or header overflow')

        page.get_by_role('button', name='打开导航', exact=True).click()
        expect(page.locator('.bio-nav-drawer').get_by_text('科研可视化图库', exact=True)).to_be_visible()
        page.locator('.bio-nav-drawer').get_by_text('科研可视化图库', exact=True).click()
        expect(page.get_by_role('heading', name='科研可视化图库', exact=True)).to_be_visible()
        page.goto(args.url, wait_until='networkidle')
        page.set_viewport_size({'width':1440,'height':1000})
        for label in ['Macro-F1', '指标表', 'Top-K 性能', '表达热图', '类别样本数']:
            page.get_by_role('button', name=label, exact=True).click()
        legend = page.locator('.class-legend-button').first
        legend.click()
        expect(legend).to_have_attribute('aria-pressed', 'false')
        expect(page.locator('.donut-label')).to_contain_text('已选类别样本')
        legend.click()
        report['checks'].append('mobile drawer and chart tabs navigate correctly')

        for dataset in datasets[:2]:
            page.locator('.header-dataset .arco-select').click()
            page.locator('.arco-select-option').filter(has_text=dataset['dataset_id'].upper()).click()
            page.wait_for_load_state('networkidle')
            expect(page.locator('.dashboard-section-caption')).to_contain_text(dataset['dataset_id'].upper())
            if dataset.get('samples') is not None:
                expect(page.locator('.summary-card').nth(1).locator('strong')).to_have_text(f"{dataset['samples']:,}")
            assert dataset['dataset_id'] == page.evaluate("JSON.parse(localStorage.getItem('genescope-dashboard-dataset-v1'))")
        report['checks'].append('dataset selection refreshes statistics and persists the selection')

        page.get_by_role('switch', name='页面动效').click()
        assert page.get_by_role('switch', name='页面动效').get_attribute('aria-checked') == 'true'
        page.get_by_role('button', name='收起侧边栏').click()
        expect(page.locator('.research-shell')).to_have_class(__import__('re').compile('sidebar-collapsed'))
        page.get_by_role('menuitem', name='基因猎手：寻找关键特征').click()
        expect(page.get_by_role('heading', name='基因猎手：寻找关键特征', exact=True)).to_be_visible()
        page.goto(args.url, wait_until='networkidle')
        page.get_by_role('button', name='开始挑战', exact=True).click()
        expect(page).to_have_url(args.url + '/games/gene-hunter')
        expect(page.get_by_role('heading', name='基因猎手：寻找关键特征', exact=True)).to_be_visible()
        report['checks'].append('motion toggle, collapsed game navigation and challenge CTA work')

        for route, heading in [('/datasets','数据集中心'),('/lab','模型实验室'),('/monitor','实时任务中心'),('/comparison','模型对比'),('/features','特征分析'),('/predict','单样本预测'),('/experiments','实验历史'),('/settings','系统设置'),('/gallery','科研可视化图库'),('/presentation','课程答辩演示')]:
            page.goto(args.url + route, wait_until='networkidle')
            expect(page.get_by_role('heading', name=heading, exact=True)).to_be_visible()
        report['checks'].append('all existing workspace routes and new gallery / presentation routes render')

        offline = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce')
        offline.route('**/api/v1/**', lambda route: route.fulfill(status=503, content_type='application/json', body='{"message":"offline acceptance"}'))
        fallback = offline.new_page()
        fallback.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        fallback.goto(args.url, wait_until='networkidle')
        expect(fallback.get_by_role('heading', name='项目总览', exact=True)).to_be_visible()
        assert fallback.locator('.summary-card strong').all_text_contents() == ['—'] * 4
        expect(fallback.get_by_text('暂无类别统计', exact=True)).to_be_visible()
        assert fallback.evaluate('document.documentElement.dataset.motion') == 'reduced'
        fallback.screenshot(path=str(output / 'offline-mobile.png'), full_page=True, animations='disabled')
        report['checks'].append('API failure shows errors, unavailable values and empty charts; reduced motion respected')
        assert not report['page_errors'], report['page_errors']
        browser.close()
    (output / 'browser-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5174')
    parser.add_argument('--browser', default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    run(parser.parse_args())
