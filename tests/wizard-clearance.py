#!/usr/bin/env python3
"""Offline wizard right-edge/hit-target regressions using the actual UI.

Run normally, or set SADLER_WORKFLOW_CSS to the previous workflow.css to expose
its failure. Native mode uses this Chromium's scrollbars. Classic mode requests
17px Chromium scrollbars. Overlay mode hides native scrollbars and places an
explicit 17px pointer-intercepting fixture over the right edge, without a gutter.
The overlay is a deterministic obstruction model, NOT native Windows/DSM proof.
"""
from pathlib import Path
import importlib.util, json, os, sys
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sadler_ui_fixture',R/'tests/ui-browser.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
OUT=R/'tests/browser-1.0.0-1';OUT.mkdir(exist_ok=True)
results=[]
baseline=os.environ.get('SADLER_WORKFLOW_CSS')
css=Path(baseline).read_text() if baseline else None

def check(name,fn):
    try:
        data=fn();results.append(dict(case=name,passed=True,measurements=data));print('PASS '+name,flush=True)
    except Exception as e:
        results.append(dict(case=name,passed=False,error=str(e)));print('FAIL '+name+': '+str(e),flush=True)

def replace_workflow_css(page):
    if css is not None:
        page.evaluate('''css=>{const el=Array.from(document.querySelectorAll('style')).find(e=>e.textContent.includes('SADLERACME WORKFLOW ARRANGEMENTS'));if(!el)throw Error('No workflow stylesheet');el.textContent=css;}''',css)

def overlay_track(page):
    page.evaluate('''()=>{
      let track=document.getElementById('fixtureScrollbar');if(track)track.remove();
      const body=document.querySelector('.workflow-body');
      if(body.scrollHeight<=body.clientHeight)return;
      const b=body.getBoundingClientRect();track=document.createElement('div');track.id='fixtureScrollbar';
      Object.assign(track.style,{position:'fixed',left:(b.right-17)+'px',top:b.top+'px',width:'17px',height:b.height+'px',background:'#777',zIndex:'1060',pointerEvents:'auto'});
      document.body.appendChild(track);
    }''')

def verify(app,logs,mode):
    p=app.page
    if logs:p.locator('#workflowViewLogs').click()
    p.locator('#wfDescription').fill('Unchanged clearance-test draft')
    p.locator('#wfKey').scroll_into_view_if_needed()
    if mode=='overlay':overlay_track(p)
    data=p.evaluate('''()=>{
      const body=document.querySelector('.workflow-body'),key=document.getElementById('wfKey');
      const b=body.getBoundingClientRect(),k=key.getBoundingClientRect();
      const x=k.right-8,y=(k.top+k.bottom)/2,hit=document.elementFromPoint(x,y);
      return {clearance:b.right-k.right,nativeGutter:body.offsetWidth-body.clientWidth,
        scrollable:body.scrollHeight>body.clientHeight,scrollLeft:body.scrollLeft,
        keyHit:hit===key,hitId:hit&&hit.id,point:{x,y},bodyHeight:b.height};
    }''')
    u.require(data['clearance']>=21,repr(data))
    u.require(data['keyHit'],'Arrow hit target obstructed: '+repr(data))
    # Exercise the arrow edge itself, not just the middle of the field.
    original=p.locator('#wfKey').input_value()
    p.mouse.click(data['point']['x'],data['point']['y']);p.keyboard.press('Escape')
    u.require(p.locator('#wfKey').input_value()==original,'Opening dropdown changed selection')
    if mode=='overlay':p.locator('#fixtureScrollbar').evaluate_all('els=>els.forEach(e=>e.remove())')
    u.box_integrity(app)
    footer_before=app.rect('.workflow-footer')
    log_before=app.rect('#workflowLogPanel') if logs else None
    body=p.locator('.workflow-body')
    for selector in ['#wfEmail','#wfToken','#workflowTokenHelp']:
        p.locator(selector).scroll_into_view_if_needed()
        v=p.locator(selector).evaluate('''el=>{const b=document.querySelector('.workflow-body').getBoundingClientRect(),r=el.getBoundingClientRect();return r.top>=b.top-1&&r.bottom<=b.bottom+1;}''')
        u.require(v,selector+' cannot be viewed within the form')
    u.require(abs(app.rect('.workflow-footer')['y']-footer_before['y'])<1,'Form scrolling moved footer')
    if logs:
        u.require(abs(app.rect('#workflowLogPanel')['y']-log_before['y'])<1,'Form scrolling moved log panel')
        r=app.rect('#workflowLogPanel');u.require(r['y']+r['height']<=footer_before['y']+1,'Log overlaps footer')
        p.locator('#workflowLogText').evaluate("e=>e.textContent='Synthetic clearance fixture line\\n'.repeat(200)")
        u.require(p.locator('#workflowLogText').evaluate('e=>e.scrollHeight>e.clientHeight'),'Long log not independently scrollable')
    u.require(p.locator('#wfDescription').input_value()=='Unchanged clearance-test draft','Draft changed')
    u.require(not app.posts,'Appearance-only fixture posted an action')
    return data

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    sizes=[(1320,780),(900,620),(900,560),(820,580),(768,680),(570,700),(390,780)]
    if os.environ.get('SADLER_CLEARANCE_QUICK'):sizes=[(900,560)]
    for width,height in sizes:
        for theme in ['dark','light']:
            for mode in ['native','classic','overlay']:
                app=u.App(browser,mode='empty',width=width,height=height,theme=theme)
                p=app.page;replace_workflow_css(p)
                if mode=='classic':p.add_style_tag(content='.workflow-body {scrollbar-width:auto;} .workflow-body::-webkit-scrollbar {width:17px;}')
                if mode=='overlay':p.add_style_tag(content='.workflow-body {scrollbar-width:none;} .workflow-body::-webkit-scrollbar {display:none;}')
                for logs in [False,True]:
                    p.locator('#setupWizard-dashboard').click();p.wait_for_timeout(50);p.locator('#workflowNext').click()
                    check(f'{width}x{height}:{theme}:{mode}:logs={logs}',lambda:verify(app,logs,mode))
                    if width==900 and height==560 and logs and mode=='classic' and not baseline:
                        p.locator('#wfKey').scroll_into_view_if_needed()
                        app.screenshot('wizard-clearance-'+theme)
                    p.locator('#fixtureScrollbar').evaluate_all('els=>els.forEach(e=>e.remove())')
                    p.locator('#workflowExit').click()
                app.close()
    browser.close()
report=dict(scope='Local Chromium actual CGI/scripts/styles; synthetic status only; overlay obstruction is a 17px fixture, not native DSM',baseline_css=baseline,cases=results)
name='BASELINE-clearance-comparison.json' if baseline else 'RESULTS-1.0.0-1-clearance.json'
(R/'tests'/name).write_text(json.dumps(report,indent=2)+'\n')
failed=sum(not r['passed'] for r in results)
print(f'{len(results)-failed}/{len(results)} scrollbar-clearance cases passed; {failed} failures.',flush=True)
sys.exit(bool(failed))
