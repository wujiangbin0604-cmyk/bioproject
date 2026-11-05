"""Gene Hunter browser acceptance. Run against npm run dev or npm run preview.

Uses the repository's existing backend/.vendor Playwright when installed.
python tests/gene_hunter_browser.py --inspect
python tests/gene_hunter_browser.py
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'backend' / '.vendor'
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
from playwright.sync_api import sync_playwright, expect


def run(args):
    output = ROOT / 'reports' / 'gene-hunter'
    output.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'page_errors': [], 'base_url': args.url}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser)
        context = browser.new_context(viewport={'width': 1440, 'height': 1050})
        # Deliberately make the platform API unavailable: game data must be local.
        context.route('**/api/v1/**', lambda route: route.fulfill(status=503, content_type='application/json', body='{"message":"offline acceptance"}'))
        page = context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        response = page.goto(args.url + '/games/gene-hunter', wait_until='networkidle')
        assert response.status == 200
        if args.inspect:
            print(json.dumps({'body': page.locator('body').inner_text()[:1800], 'errors': report['page_errors']}, ensure_ascii=True))
            page.screenshot(path=str(output / 'desktop-inspect.png'), full_page=True, animations='disabled')
        expect(page.get_by_role('heading', name='基因猎手：寻找关键特征', exact=True)).to_be_visible()
        page.screenshot(path=str(output / 'desktop-ready.png'), full_page=True, animations='disabled')
        if args.inspect:
            print(json.dumps({'buttons': page.get_by_role('button').all_text_contents(), 'rows': page.locator('[data-gene]').count(), 'body_width': page.evaluate('document.body.scrollWidth'), 'viewport': 1440, 'errors': report['page_errors']}, ensure_ascii=False))
            browser.close()
            return

        expect(page.get_by_test_id('timer')).to_have_text('01:00')
        assert page.locator('[data-gene]:enabled').count() == 0
        assert page.locator('.gh-top-list').count() == 0
        report['checks'].append('direct route refresh works; answer ranks hidden and input disabled before start; independent of API')

        page.clock.install()
        page.get_by_role('button', name='开始挑战', exact=True).click()
        page.locator('[data-gene="KRT19"] .gh-cell').first.hover()
        expect(page.get_by_text('KRT19 · A1 · 表达值', exact=False)).to_be_visible()
        page.locator('[data-gene="KRT19"]').click()
        expect(page.get_by_test_id('total-score')).to_have_text('800')
        expect(page.locator('.gh-last-feedback')).to_contain_text('关键特征 +800')
        assert page.locator('[data-gene="KRT19"]').is_disabled()
        page.locator('[data-gene="KRT19"]').dispatch_event('click')
        expect(page.get_by_test_id('total-score')).to_have_text('800')
        assert page.locator('.gh-selected-high').count() == 1
        report['checks'].append('cell tooltip, row highlight, immediate feedback and duplicate-score guard')

        for gene, score in [('EGFR','1,760'), ('MUC1','2,960'), ('SLC2A1','4,560'), ('EPCAM','6,160')]:
            page.locator(f'[data-gene="{gene}"]').click()
            expect(page.get_by_test_id('total-score')).to_have_text(score)
        expect(page.get_by_test_id('combo')).to_have_text('5连击')
        page.screenshot(path=str(output / 'desktop-playing.png'), full_page=True, animations='disabled')
        page.locator('[data-gene="B2M"]').click()
        expect(page.get_by_test_id('total-score')).to_have_text('6,460')
        expect(page.get_by_test_id('combo')).to_have_text('0连击')
        page.locator('[data-gene="ACTB"]').click()
        expect(page.get_by_test_id('total-score')).to_have_text('6,460')
        expect(page.locator('.gh-last-feedback')).to_contain_text('连击重置')
        report['checks'].append('exact combo score sequence 800/960/1200/1600/1600; medium +300; low +0 resets combo')

        page.clock.fast_forward(61000)
        expect(page.get_by_test_id('timer')).to_have_text('00:00')
        expect(page.locator('.gh-top-list li')).to_have_count(5)
        expect(page.locator('.gh-round-summary')).to_contain_text('找到 5 / 5')
        assert page.locator('[data-gene]:enabled').count() == 0
        page.locator('[data-gene="VIM"]').dispatch_event('click')
        expect(page.get_by_test_id('total-score')).to_have_text('6,460')
        page.screenshot(path=str(output / 'desktop-result.png'), full_page=True, animations='disabled')
        report['checks'].append('clock expiry submits once, reveals Top5 and 3 stars, disables further scoring')

        levels = [
            ['ESR1','FOXA1','GATA3','PGR','ERBB2'],
            ['ALB','AFP','GPC3','CYP3A4','APOA1'],
            ['NKX2-1','SFTPC','KRT5','TP63','KRT14'],
            ['PAX8','CA9','KRT7','SLC34A1','EGLN3'],
        ]
        for level_number, genes in enumerate(levels, start=2):
            page.get_by_role('button', name='进入下一关', exact=True).click()
            expect(page.get_by_test_id('combo')).to_have_text('0连击')
            assert page.locator('[data-selected="true"]').count() == 0
            page.get_by_role('button', name=f'开始第 {level_number} 关', exact=True).click()
            for gene in genes:
                page.locator(f'[data-gene="{gene}"]').click()
            page.get_by_role('button', name='提交本关 · 揭晓排名', exact=True).click()
            expect(page.locator('.gh-round-summary')).to_contain_text('找到 5 / 5')
        page.get_by_role('button', name='查看挑战总结', exact=True).click()
        expect(page.locator('.gh-complete')).to_contain_text('累计 31,100 分')
        expect(page.locator('.gh-complete')).to_contain_text('本次 15 / 15 星')
        expect(page.locator('.gh-growth')).to_contain_text('Lv.4')
        expect(page.locator('.gh-personal-best')).to_contain_text('31,100')
        report['checks'].append('all five rounds complete, reset correctly, aggregate score 31100 and 15 stars, unlock Lv4')
        page.screenshot(path=str(output / 'desktop-complete.png'), full_page=True, animations='disabled')
        page.get_by_role('button', name='再挑战一次', exact=True).click()
        expect(page.get_by_test_id('total-score')).to_have_text('0')
        expect(page.locator('.gh-growth')).to_contain_text('15 / 15')
        page.reload(wait_until='networkidle')
        expect(page.locator('.gh-personal-best')).to_contain_text('31,100')
        expect(page.locator('.gh-growth')).to_contain_text('15 / 15')
        report['checks'].append('restart clears run; reload preserves best record and per-level stars')

        page.get_by_role('button', name='第一次玩？查看指南', exact=False).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        page.get_by_role('button', name='全局搜索', exact=True).click()
        page.get_by_role('textbox', name='搜索平台内容').fill('基因猎手')
        expect(page.locator('.search-results')).to_contain_text('基因猎手：寻找关键特征')
        page.keyboard.press('Escape')
        page.get_by_role('menuitem', name='系统设置', exact=True).click()
        expect(page).to_have_url(args.url + '/settings')
        page.get_by_role('menuitem', name='基因猎手：寻找关键特征', exact=True).click()
        expect(page).to_have_url(args.url + '/games/gene-hunter')
        report['checks'].append('help modal, sidebar navigation and global search connected')

        for width, height, name in [(1024,900,'tablet'), (390,844,'mobile')]:
            page.set_viewport_size({'width':width,'height':height})
            page.screenshot(path=str(output / f'{name}.png'), full_page=True, animations='disabled')
            if page.evaluate('document.documentElement.scrollWidth') > width:
                print(json.dumps(page.evaluate('''() => [...document.querySelectorAll('body *')].map(el => ({tag:el.tagName,cls:el.className,right:el.getBoundingClientRect().right,width:el.getBoundingClientRect().width})).filter(el => el.right > innerWidth + 1).slice(0,25)'''),ensure_ascii=True))
            assert page.evaluate('document.documentElement.scrollWidth') <= width, f'overflow at {width}'
        board = page.locator('.gh-board-scroll')
        board.evaluate('el => { el.scrollLeft = el.scrollWidth; }')
        gene_left = page.locator('.gh-gene-label').first.bounding_box()['x']
        assert abs(gene_left - board.bounding_box()['x']) < 10, 'gene names should stay visible while scrolling'
        board.evaluate('el => { el.scrollLeft = 0; }')
        page.screenshot(path=str(output / 'mobile.png'), full_page=True, animations='disabled')
        page.emulate_media(reduced_motion='reduce')
        expect(page.locator('html')).to_have_attribute('data-motion','reduced')
        page.get_by_role('button', name='开始挑战', exact=True).click()
        page.locator('[data-gene="KRT19"]').focus()
        page.keyboard.press('Enter')
        expect(page.get_by_test_id('total-score')).to_have_text('800')
        assert page.locator('.gh-particles').count() == 0
        report['checks'].append('1024/390 layouts without page overflow; reduced motion and keyboard selection work')
        report['checks'].append('mobile heatmap scrolls horizontally while gene names remain fixed')
        assert not report['page_errors'], report['page_errors']
        browser.close()
    (output / 'browser-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:5173')
    parser.add_argument('--browser',default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    parser.add_argument('--inspect',action='store_true')
    run(parser.parse_args())
