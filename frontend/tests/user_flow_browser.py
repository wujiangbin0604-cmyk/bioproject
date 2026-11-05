"""Browser acceptance for the reusable homepage onboarding flow."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / '.vendor'))
from playwright.sync_api import sync_playwright, expect


def run(args):
    output = ROOT / 'reports' / 'user-flow-guide'
    output.mkdir(parents=True, exist_ok=True)
    report = {'base_url': args.url, 'checks': [], 'page_errors': []}

    def api_fixture(route):
        path = urlparse(route.request.url).path
        if path == '/api/v1/health':
            body = {'status': 'available', 'data': {'api': 'ok', 'model_available': False}}
        elif path in ['/api/v1/datasets', '/api/v1/models', '/api/v1/experiments']:
            body = {'items': []}
        else:
            body = {'dataset_id': 'pancan', 'heatmap': None}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.route('**/api/v1/**', api_fixture)
        page = context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        page.goto(args.url, wait_until='networkidle')
        flow = page.get_by_role('region', name='一、推荐的用户进入流程', exact=True)
        expect(flow).to_be_attached()
        if args.inspect:
            print(json.dumps({'headings': page.get_by_role('heading').all_text_contents(), 'dialogs': page.get_by_role('dialog').all_text_contents(), 'errors': report['page_errors']}, ensure_ascii=True))
            page.screenshot(path=str(output / 'first-visit.png'), full_page=True, animations='disabled')
            browser.close()
            return
        expect(page.get_by_role('dialog')).to_contain_text('欢迎引导 · 从这里开始')
        page.get_by_role('button', name='我知道了，开始探索', exact=True).click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        assert page.evaluate("localStorage.getItem('genescope-welcome-guide-v1')") == 'true'
        report['checks'].append('first visit shows welcome; dismiss persists acknowledgement')

        expect(flow.locator('.ufg-timeline > li')).to_have_count(4)
        expect(flow.locator('.ufg-arrow')).to_have_count(3)
        expect(flow.locator('.ufg-tags .arco-tag')).to_have_text(['多数据集', '模型实验', '特征分析'])
        for item in flow.locator('[data-flow-reveal]').all():
            item.scroll_into_view_if_needed()
            expect(item).to_have_attribute('data-revealed', 'true')
        flow.screenshot(path=str(output / 'desktop-flow.png'), animations='disabled', style='.bio-topbar { visibility: hidden !important; }')
        report['checks'].append('four ordered steps, three arrows, exact copy and tags; steps reveal on scroll')

        learn = page.get_by_role('button', name='了解欢迎引导设计', exact=True)
        learn.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_role('dialog')).to_contain_text('为什么先看欢迎引导？')
        page.get_by_role('dialog').screenshot(path=str(output / 'welcome-modal.png'), animations='disabled')
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(learn).to_be_focused()
        learn.press('Enter')
        expect(page.get_by_role('dialog')).to_be_visible()
        page.get_by_role('dialog').get_by_role('link', name='先玩基因猎手', exact=True).click()
        expect(page).to_have_url(args.url + '/games/gene-hunter')
        expect(page.get_by_role('button', name='开始挑战', exact=True)).to_be_visible()
        report['checks'].append('learn button reopens modal; Escape restores focus; keyboard opens; modal game action navigates')

        page.goto(args.url, wait_until='networkidle')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        page.get_by_role('link', name='进入基因猎手小游戏', exact=True).click()
        expect(page).to_have_url(args.url + '/games/gene-hunter')
        page.goto(args.url, wait_until='networkidle')
        page.get_by_role('link', name='探索 GeneScope 其他科研功能', exact=True).click()
        expect(page).to_have_url(args.url + '/datasets')
        report['checks'].append('returning visits do not auto-open; flow step game and dataset links work')

        for width, height, name in [(1024, 900, 'tablet'), (390, 844, 'mobile'), (320, 740, 'small-mobile')]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(args.url, wait_until='networkidle')
            for item in flow.locator('[data-flow-reveal]').all():
                item.scroll_into_view_if_needed()
                expect(item).to_have_attribute('data-revealed', 'true')
            flow.screenshot(path=str(output / f'{name}-flow.png'), animations='disabled', style='.bio-topbar { visibility: hidden !important; }')
            assert page.evaluate('document.documentElement.scrollWidth') <= width, f'page overflows at {width}'
            box = flow.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            page.get_by_role('button', name='了解欢迎引导设计', exact=True).click()
            expect(page.get_by_role('dialog')).to_be_visible()
            assert page.get_by_role('dialog').bounding_box()['width'] <= width
            page.get_by_role('button', name='我知道了，开始探索', exact=True).click()
        report['checks'].append('1024, 390 and 320 pixel layouts and modal fit without horizontal overflow')

        page.emulate_media(reduced_motion='reduce')
        expect(flow).to_have_attribute('data-reveal', 'disabled')
        for item in flow.locator('[data-flow-reveal]').all():
            assert item.evaluate("el => getComputedStyle(el).opacity") == '1'
        assert flow.locator('.ufg-arrow > span').first.evaluate("el => getComputedStyle(el).animationName") == 'none'
        report['checks'].append('reduced motion keeps every step visible and disables arrow animation')

        unavailable = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
        unavailable.route('**/api/v1/**', lambda route: route.fulfill(status=503, body='{}', content_type='application/json'))
        unavailable.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('unavailable storage'); }});")
        fallback = unavailable.new_page()
        fallback.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        fallback.goto(args.url, wait_until='networkidle')
        fallback.get_by_role('button', name='我知道了，开始探索', exact=True).click()
        fallback_flow = fallback.get_by_role('region', name='一、推荐的用户进入流程', exact=True)
        expect(fallback_flow).to_have_attribute('data-reveal', 'disabled')
        expect(fallback_flow.get_by_role('button', name='了解欢迎引导设计')).to_be_visible()
        fallback_flow.get_by_role('button', name='了解欢迎引导设计').click()
        expect(fallback.get_by_role('dialog')).to_be_visible()
        report['checks'].append('onboarding remains usable when browser storage and platform API are unavailable')
        assert not report['page_errors'], report['page_errors']
        browser.close()

    (output / 'browser-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5179')
    parser.add_argument('--browser', default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    parser.add_argument('--inspect', action='store_true')
    run(parser.parse_args())
