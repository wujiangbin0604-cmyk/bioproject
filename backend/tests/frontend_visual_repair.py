"""Two-pass visual repair acceptance: real frames, actual chart interactions and retained workflows."""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/visual-repair'
BASE='http://127.0.0.1:5174'
EDGE=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'


def run():
    OUT.mkdir(exist_ok=True)
    errors=[]; report={'checks':[], 'frames':[], 'viewports':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=EDGE)
        page=browser.new_page(viewport={'width':1440,'height':900},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(BASE,wait_until='networkidle')
        page.wait_for_timeout(800)

        def frame(name, locator=None):
            path=OUT/(name+'.png')
            if locator is None: page.screenshot(path=str(path),full_page=True)
            else: locator.screenshot(path=str(path))
            report['frames'].append(name)

        cards=page.locator('.overview-stats .animated-stat')
        assert cards.count()==4
        data=page.request.get(BASE+'/api/v1/datasets').json()['items']
        assert cards.nth(0).locator('.stat-copy strong').inner_text()==str(sum(d['status']=='ready' for d in data))
        fonts=page.locator('.stat-copy>span,.stat-copy small,.small-note').evaluate_all('els=>els.map(e=>parseFloat(getComputedStyle(e).fontSize))')
        assert min(fonts)>=12,fonts
        report['checks'].append('real API statistic and caption minimum 12px')
        start=cards.first.bounding_box()
        frame('stat-hover-before',cards.first)
        cards.first.hover()
        page.wait_for_timeout(80); frame('stat-hover-mid',cards.first)
        page.wait_for_timeout(160); frame('stat-hover-after',cards.first)
        end=cards.first.bounding_box()
        assert 2.5<=start['y']-end['y']<=4.5,(start,end)
        scale=cards.first.locator('.stat-icon').evaluate('e=>getComputedStyle(e).transform')
        assert '1.05' in scale,scale
        report['checks'].append('hover moves statistic card 4px and scales icon to 1.05')
        page.get_by_label('查看已就绪数据集详情',exact=True).click()
        page.wait_for_url('**/datasets')
        page.goto(BASE,wait_until='networkidle')
        quick=page.locator('.quick-start').first
        quick.hover(); page.wait_for_timeout(230)
        assert '1.05' in quick.locator('svg').first.evaluate('e=>getComputedStyle(e).transform')
        frame('quick-start-hover',quick)
        page.mouse.move(750,65)
        report['checks'].append('stat navigation and restrained quick-start icon hover')

        dna=page.locator('.dna-hero')
        offset1=dna.locator('.dna-flow').first.evaluate('e=>getComputedStyle(e).strokeDashoffset')
        frame('dna-frame-1',dna)
        page.wait_for_timeout(450)
        offset2=dna.locator('.dna-flow').first.evaluate('e=>getComputedStyle(e).strokeDashoffset')
        frame('dna-frame-2',dna)
        assert offset1!=offset2,(offset1,offset2)
        dna.scroll_into_view_if_needed()
        dna_box=dna.bounding_box()
        page.mouse.move(dna_box['x']+dna_box['width']*.65,dna_box['y']+dna_box['height']*.5)
        assert dna.evaluate("e=>e.style.getPropertyValue('--dna-x')") not in ['', '0px']
        report['dna_stroke_offsets']=[offset1,offset2]
        report['checks'].append('continuous helix highlight flow and real pointer parallax')

        panel=page.locator('.overview-chart-panel')
        panel.scroll_into_view_if_needed()
        frame('tab-before',panel)
        page.get_by_text('特征选择',exact=True).first.click()
        page.wait_for_timeout(35)
        assert page.locator('.crossfade-panel').get_attribute('data-phase')=='exit'
        frame('tab-exit',panel)
        page.wait_for_timeout(350)
        assert page.locator('.crossfade-panel').evaluate('e=>getComputedStyle(e).opacity')=='1'
        frame('tab-after',panel)
        # Rapid reversal must not leave the outgoing panel invisible.
        page.get_by_text('数据分布',exact=True).click(); page.wait_for_timeout(25)
        page.get_by_text('特征选择',exact=True).first.click(); page.wait_for_timeout(400)
        assert page.locator('.crossfade-panel').evaluate('e=>getComputedStyle(e).opacity')=='1'
        page.get_by_text('分类性能',exact=True).click(); page.wait_for_timeout(800)
        report['checks'].append('fade-out, data swap, fade-in and rapid tab reversal')

        canvas=panel.locator('canvas').first
        bounds=canvas.bounding_box()
        page.mouse.move(bounds['x']+110,bounds['y']+120)
        page.wait_for_timeout(250)
        frame('chart-real-tooltip',panel)
        page.mouse.move(750,65); page.wait_for_timeout(100)
        before=hashlib.sha256(canvas.screenshot()).hexdigest()
        page.mouse.click(bounds['x']+40,bounds['y']+15)
        page.mouse.move(750,65); page.wait_for_timeout(450)
        after=hashlib.sha256(canvas.screenshot()).hexdigest()
        assert before!=after
        frame('chart-legend-toggled',panel)
        with page.expect_download() as download:
            page.mouse.click(bounds['x']+bounds['width']-14,bounds['y']+12)
        download.value.save_as(str(OUT/'real-chart-export.png'))
        report['checks'].append('actual ECharts tooltip, legend toggle and PNG export')

        page.locator('.bio-navigation .arco-menu-inline-header').click()
        page.get_by_text('原研究总览',exact=True).wait_for()
        page.locator('.bio-navigation .arco-menu-inline-header').click()
        page.get_by_text('原研究总览',exact=True).wait_for(state='hidden')
        width1=canvas.bounding_box()['width']
        page.get_by_label('收起侧边栏',exact=True).click(); page.wait_for_timeout(450)
        assert canvas.bounding_box()['width']>width1
        page.get_by_label('展开侧边栏',exact=True).click()
        report['checks'].append('submenu expand/collapse and responsive chart resize')

        page.goto(BASE+'/predict',wait_until='networkidle')
        upload=page.locator('.csv-upload-area')
        transfer=page.evaluate_handle("new DataTransfer()")
        upload.dispatch_event('dragenter',{'dataTransfer':transfer})
        assert 'is-dragging' in upload.get_attribute('class')
        frame('upload-drag-enter',upload)
        upload.dispatch_event('dragleave',{'dataTransfer':transfer})
        assert 'is-dragging' not in upload.get_attribute('class')
        transfer=page.evaluate_handle("()=>{const d=new DataTransfer();d.items.add(new File(['A,A\\n1,2\\n'],'invalid.csv',{type:'text/csv'}));return d}")
        upload.dispatch_event('drop',{'dataTransfer':transfer})
        page.get_by_text('CSV存在重复特征列',exact=True).wait_for()
        frame('upload-validation-error')
        report['checks'].append('drag enter/leave highlighting and real drop validation error')

        page.goto(BASE,wait_until='networkidle')
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.dna-hero').get_attribute('data-active')=='false'
        offset1=page.locator('.dna-hero .dna-flow').first.evaluate('e=>getComputedStyle(e).strokeDashoffset')
        page.wait_for_timeout(250)
        offset2=page.locator('.dna-hero .dna-flow').first.evaluate('e=>getComputedStyle(e).strokeDashoffset')
        assert offset1==offset2
        report['checks'].append('OS reduced motion stops strand flow and micro animations')
        page.emulate_media(reduced_motion='no-preference')

        for width,height in [(1440,900),(1920,1080),(1280,800),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            page.goto(BASE,wait_until='networkidle')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            page.screenshot(path=str(OUT/f'after-{width}-{height}.png'),full_page=True,animations='disabled')
            report['viewports'].append([width,height])
        page.set_viewport_size({'width':1440,'height':900})
        tasks=page.request.get(BASE+'/api/v1/experiments?status=completed&dataset_id=gse45827').json()['items']
        config={**tasks[0]['experiment_config'],'selection':'none','algorithms':['random_forest'],'folds':5,'repeats':2,'n_estimators':300}
        response=page.request.post(BASE+'/api/v1/experiments',data=config)
        assert response.status==202,response.text()
        task=response.json()['task_id']; report['live_motion_task']=task
        try:
            page.goto(BASE+'/monitor/'+task,wait_until='domcontentloaded')
            page.locator('.training-node.node-active').first.wait_for()
            progress=page.locator('.monitor-progress-card')
            frame('monitor-live-1',progress); page.wait_for_timeout(350); frame('monitor-live-2',progress)
            page.get_by_role('button',name='取消任务',exact=True).click()
            page.get_by_role('button',name='确定',exact=True).click()
            page.locator('.status-cancelled').first.wait_for(timeout=30000)
            frame('monitor-cancelled',progress)
            report['checks'].append('real running stage pulse, progress and actual cancellation feedback')
        finally: page.request.post(BASE+'/api/v1/experiments/'+task+'/cancel')
        report['page_errors']=errors
        assert not errors,errors
        browser.close()
    (OUT/'interaction-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':run()
