#!/usr/bin/env python3
"""1.0.0-1 Chromium UI fixtures; actual CGI markup and shipped JS/CSS.
All requests intercepted locally; no real DSM/ACME credentials or services.
Run: python3 tests/ui-browser.py (CHROMIUM defaults to /usr/bin/chromium).
"""
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import importlib.util,json,time,os,re
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1]
OUT=R/'tests/browser-1.0.0-1';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('regression_fixture',R/'tests/regression.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
f=m.Regression();f.setUp()
CONFIG=dict(email='owner@example.com',domains=['lab.example.com','*.lab.example.com'],key_type='ec-384',cert_desc='SadlerACME Lab',default_on_create='0',auto_renew='1',dns_sleep='60')
EMPTY=dict(CONFIG,email='',domains=[],cert_desc='SadlerACME wildcard')
HTML={}
try:
 for key,config in [('configured',dict(CONFIG,cf_token=m.TOKEN)),('empty',dict(EMPTY,cf_token=''))]:
  (f.etc/'settings.json').write_text(json.dumps(config))
  text=f.request();HTML[key]=text[text.index('<!doctype'):]
finally:f.doCleanups()
NOW=str(int(time.time()))
GOOD=dict(package_running='yes',worker_available='yes',worker_last='2026-10-04 10:00:00',worker_epoch=NOW,queue_state='active',timer_state='active',scheduler_status='Installed and enabled',setup_temporary='no',uninstall_ready='no',state='success',message='Renewal check complete; valid certificate verified in DSM',local_cert_available='yes',dsm_match='yes',dsm_id='fixture',dsm_default='Yes',dsm_default_raw='true',restore_requires_issue='no',setup_required='no',last_action='check',last_run='2026-10-04 10:00:00',checked_epoch=NOW,server_epoch=NOW,dsm_freshness='fresh',next_auto_stale='no',auto_renew='1',auto_renew_text='Enabled — every 6 hours',next_auto=str(int(time.time())+21600),fingerprint='AA:BB:CC:DD:EE:FF',sans='DNS:lab.example.com, DNS:*.lab.example.com',issuer="Let's Encrypt (synthetic fixture)",not_before='Oct 1 2026 GMT',not_after='Jan 1 2027 GMT',days='89',mailplus_reload='Not required yet',last_issue='2026-10-01 12:10:12',last_renewal='Not recorded',last_deploy='2026-10-01 12:10:14',last_verified='2026-10-04 10:00:00',last_staging='2026-10-01 11:54:54',deployment_method='Local DSM WebAPI creation',scheduler_last='2026-10-04 10:00:00',scheduler_detail='Installed and enabled',log='Synthetic UI test log; no real certificate operation.\n'*4)
FRESH=dict(GOOD,state='idle',message='Waiting for configuration',setup_required='yes',worker_available='no',worker_last='Not detected yet',worker_epoch='',queue_state='Unknown',timer_state='Unknown',scheduler_status='Not checked',checked_epoch='',dsm_freshness='unverified',last_action='None',last_run='Never',local_cert_available='no',dsm_match='unknown',dsm_id='',dsm_default='Unknown',dsm_default_raw='',fingerprint='',sans='',issuer='',not_before='',not_after='',days='',log='',last_issue='Not recorded',last_renewal='Not recorded',last_deploy='Not recorded',last_verified='Not recorded',last_staging='Not recorded',deployment_method='Not recorded',scheduler_last='Not checked')
URL='http://127.0.0.1/webman/3rdparty/sadleracme/index.cgi?SynoToken=fixture'
results=[];failures=[]
def check(name,fn):
 try:fn();results.append(dict(case=name,passed=True));print('PASS '+name,flush=True)
 except Exception as e:results.append(dict(case=name,passed=False));failures.append(dict(case=name,error=str(e)));print('FAIL '+name+': '+str(e)[:300],flush=True)
def require(test,message):
 if not test:raise AssertionError(message)
class App:
 def __init__(self,browser,mode='configured',width=1320,height=780,theme=None,blocked=False):
  self.ctx=browser.new_context(viewport=dict(width=width,height=height))
  self.posts=[];self.errors=[];self.receipts={};self.status=dict(FRESH if mode=='empty' else GOOD);self.config=dict(EMPTY if mode=='empty' else CONFIG);self.mode=mode
  self.blocked=blocked;self.storage={'local':{},'session':{}}
  if theme is not None:self.storage['local']['sadleracme.theme']=theme
  self.load()
 def request(self,url,opts):
  u=urlsplit(url);q=parse_qs(u.query);api=q.get('api',[''])[0]
  if opts.get('method')=='POST':
   body=opts.get('body') or ''
   data=json.loads(body) if body.startswith('{') else {k:v[0] for k,v in parse_qs(body).items()}
   self.posts.append(data);action=data.get('action');identifier='ui-'+str(len(self.posts))
   if action=='automation-intent':return dict(ok=True)
   self.receipts[identifier]=dict(ok=True,job_id=identifier,result='completed',message='Fixture completed')
   return dict(ok=True,job_id=identifier,message='Fixture queued')
  if api=='status':return self.status
  if api=='settings':return dict(ok=True,config=self.config,has_token=self.mode!='empty',settings_hash='fixture-hash')
  if api=='job':return self.receipts.get(q.get('id',[''])[0],dict(ok=True,result='pending'))
  return dict(ok=False,message='Unexpected fixture request')
 def load(self):
  # The managed Chromium blocks all URL navigation. Use about:blank with
  # set_content and in-memory fetch/storage fixtures; do not alter its policy.
  # This is rendered DOM/layout plus JS contract evidence, not native storage.
  self.page=self.ctx.new_page();self.page.set_default_timeout(5000)
  self.page.on('pageerror',lambda error:self.errors.append(str(error)))
  self.page.on('dialog',lambda d:d.accept());self.page.route('**/*',lambda route:route.abort())
  self.page.expose_function('__uiRequest',self.request)
  html=HTML[self.mode]
  scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
  html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
  html=re.sub(r'<link\b[^>]*rel="stylesheet"[^>]*>','',html)
  html=html.replace('nav-icons.svg#','#')
  self.page.set_content(html)
  symbols=(R/'src/ui/nav-icons.svg').read_text().replace('<svg xmlns=', '<svg style="position:absolute;width:0;height:0" aria-hidden="true" xmlns=')
  self.page.evaluate('(svg)=>document.body.insertAdjacentHTML("afterbegin",svg)',symbols)
  for css in ['layout.css','workflow.css']:self.page.add_style_tag(content=(R/'src/ui'/css).read_text())
  self.page.evaluate('''data=>{
    window.__uiStorage=data.storage;
    for(const [property,key] of [['localStorage','local'],['sessionStorage','session']]){
      Object.defineProperty(window,property,{configurable:true,get(){
        if(data.blocked&&key==='local')throw Error('Storage blocked by fixture');
        const values=window.__uiStorage[key];
        return {getItem:k=>Object.prototype.hasOwnProperty.call(values,k)?values[k]:null,
          setItem:(k,v)=>{values[k]=String(v);},removeItem:k=>{delete values[k];}};
      }});
    }
    window.fetch=async(url,opts={})=>{const data=await window.__uiRequest(String(url),{method:opts.method||'GET',body:opts.body?String(opts.body):''});return {ok:data.ok!==false,status:data.ok===false?400:200,json:async()=>data,text:async()=>JSON.stringify(data)};};
  }''',dict(storage=self.storage,blocked=self.blocked))
  self.page.add_script_tag(path=str(R/'src/ui/theme.js'))
  for js in scripts:self.page.add_script_tag(content=js)
  self.page.add_script_tag(path=str(R/'src/ui/workflow.js'))
  self.page.wait_for_selector('#workflowModal',state='attached');self.page.wait_for_timeout(100)
 def reopen(self):
  self.storage=self.page.evaluate('window.__uiStorage');self.page.close();self.load()
 def tab(self,name):
  button=self.page.locator('.tabbtn[data-tab="'+name+'"]')
  if not button.is_visible():self.page.locator('#menuToggle').click()
  button.click();self.page.wait_for_timeout(30)
 def theme(self,name):
  if self.page.locator('html').get_attribute('data-theme')!=name:self.page.locator('#themeToggle').click()
 def screenshot(self,name):self.page.screenshot(path=str(OUT/(name+'.png')))
 def rect(self,selector):return self.page.locator(selector).bounding_box()
 def close(self):self.ctx.close()

def box_integrity(app):
 p=app.page
 bad=p.evaluate('''() => { const w=innerWidth, errors=[];
 const root=document.documentElement;if(root.scrollWidth>w+1)errors.push('horizontal document overflow');
 for(const e of document.querySelectorAll('input:not([type="hidden"]),select,textarea,button')){
  const r=e.getBoundingClientRect();if(!r.width||!r.height||!e.offsetParent)continue;
  if(r.left< -1||r.right>w+1)errors.push((e.id||e.textContent||e.name)+' horizontal overflow');
 }return errors;}''')
 require(not bad,repr(bad));require(not app.errors,repr(app.errors))

def fit_settings(app):
 app.tab('settings');box_integrity(app)
 r=app.rect('#certificateOperations');h=app.page.viewport_size['height']
 require(r['y']+r['height']<=h+1,f"Settings actions bottom={r['y']+r['height']} viewport={h}")
 require(app.page.locator('#certDescription').input_value()=='SadlerACME Lab','description retained')
 require(app.rect('#certDescription')['y']<app.rect('#certEmail')['y'],'description before account email')
 require(app.page.locator('#certificateSettings').evaluate('e=>getComputedStyle(e.querySelector("input")).fontSize')=='14px','input size should be retained')

def fit_log(app,lines=300):
 app.status['log']=''.join(f'{i:04} synthetic log entry '+('abcdefghij '*15)+'\n' for i in range(lines))
 # Uses existing polling function by a visibility event; no action POST.
 app.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
 app.page.wait_for_timeout(70);app.tab('logs');box_integrity(app)
 r=app.rect('#fullLog');h=app.page.viewport_size['height']
 require(r['y']+r['height']<=h-3,f'log bottom {r} screen={h}')
 sc=app.page.locator('#mainContent').evaluate('e=>({client:e.clientHeight,scroll:e.scrollHeight})')
 require(sc['scroll']<=sc['client']+1,repr(sc))
 if lines>20:require(app.page.locator('#fullLog').evaluate('e=>e.scrollHeight>e.clientHeight'),'Log must own long-text scrollbar')
 require(app.rect('#logFilter')['height']>=29,'toolbar input preserved')

def wizard_step(app,n,logs=False):
 p=app.page
 if not p.locator('#workflowModal').is_visible():p.locator('#setupWizard-dashboard').click();p.wait_for_timeout(80)
 p.evaluate('''n=>{document.querySelectorAll('[data-workflow-step]').forEach(e=>e.hidden=Number(e.dataset.workflowStep)!==n);
 document.getElementById('workflowStep').textContent='Step '+(n+1)+' of 5';
 document.getElementById('workflowHeading').textContent=['Choose setup','Certificate settings','Start background processing','Test and apply','Finish setup'][n];
 document.getElementById('workflowWorkerControls').hidden=n<2;
 document.getElementById('workflowWorkerReady').hidden=n<2;
 document.getElementById('workflowReview').textContent='lab.example.com\\nDescription: SadlerACME Lab\\nKey: ec-384\\nExisting DSM certificate ID: fixture';
 document.getElementById('workflowNewActions').hidden=false;
 document.getElementById('workflowRestoreActions').hidden=true;
 }''',n)
 if logs and p.locator('#workflowLogPanel').is_hidden():p.locator('#workflowViewLogs').click();p.wait_for_timeout(70)
 if not logs and p.locator('#workflowLogPanel').is_visible():p.locator('#workflowViewLogs').click()
 p.locator('#workflowLogText').evaluate("e=>e.textContent='Synthetic test line\\n'.repeat(300)")
 p.locator('#workflowWizardStatus').evaluate("e=>{e.textContent='Example success message. Production settings and DSM certificate are unchanged.';e.className='workflow-status success';}")
 box_integrity(app)
 r=app.rect('.workflow-dialog');exit=app.rect('#workflowExit');h=p.viewport_size['height']
 require(r['y']>=0 and r['y']+r['height']<=h+1,repr(r))
 require(exit['y']>=0 and exit['y']+exit['height']<=h,repr(exit))
 if logs:
  lr=app.rect('#workflowLogText');require(lr['y']+lr['height']<=exit['y'], 'wizard log overlaps footer')
  require(p.locator('#workflowLogText').evaluate('e=>e.scrollHeight>e.clientHeight'),'wizard log owns scrollbar')
  require(p.locator('.workflow-dialog').evaluate('e=>e.scrollHeight<=e.clientHeight+1'),'wizard outer dialog should not scroll')

if __name__ == "__main__":
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
   app=App(browser,mode='empty')
   check('fresh Dashboard starts without auto-wizard or failing refresh',lambda:(require(app.page.locator('.tabbtn.active').get_attribute('data-tab')=='dashboard','not Dashboard'),require(not app.page.locator('#workflowModal').is_visible(),'wizard auto-opened'),require(not app.posts,'fresh page posted actions'),require('Setup Wizard' in app.page.locator('#statusFreshness').inner_text(),'missing setup message')))
   for theme in ['dark','light']:
    app.theme(theme);app.screenshot('empty-dashboard-'+theme)
   app.close()
   for width,height in [(1320,780),(1188,708),(1024,720),(900,620),(820,680),(768,680),(570,700),(390,780)]:
    app=App(browser,width=width,height=height)
    for theme in ['dark','light']:
     app.theme(theme)
     for tab in ['dashboard','settings','automation','backup','uninstall','logs','about']:
      app.tab(tab);check(f'{width}x{height}:{theme}:{tab}:bounds',lambda:box_integrity(app))
     if width>=1024:check(f'{width}x{height}:{theme}:settings-fit',lambda:fit_settings(app))
     check(f'{width}x{height}:{theme}:long-log-fit',lambda:fit_log(app))
     if width in [1320,390]:
      app.screenshot(f'{width}-logs-{theme}');app.tab('settings');app.screenshot(f'{width}-settings-{theme}')
    # Active Logs resizes with the window including toolbar wrap.
    app.tab('logs');app.page.set_viewport_size(dict(width=width,height=height-100))
    check(f'{width}:resized-log',lambda:fit_log(app))
    app.close()
   # Fresh settings should not need scrolling just for a redundant Never/status row.
   for width,height in [(1320,780),(1188,708),(1024,720)]:
    app=App(browser,mode='empty',width=width,height=height)
    for theme in ['dark','light']:
     app.theme(theme);app.tab('settings')
     def empty_fit():
      r=app.rect('#certificateOperations');require(r['y']+r['height']<=height-3,repr(r))
      require(app.page.locator('#settingsWorkerNotice').is_visible(),'missing onboarding notice')
      require(app.page.locator('#workflowActivity').is_hidden(),'redundant empty activity row')
     check(f'{width}x{height}:{theme}:empty-settings-fit',empty_fit)
     if width==1188:app.screenshot('empty-settings-1188-'+theme)
    app.close()
   app=App(browser,mode='empty')
   def preserve_error():
    app.status.update(state='error',message='Synthetic permission error: request rejected',last_action='test')
    app.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))");app.page.wait_for_timeout(100)
    require('Synthetic permission error' in app.page.locator('#statusMessage').inner_text(),'real failure hidden')
    app.tab('settings');require(app.page.locator('#workflowActivity').is_visible(),'failure activity hidden')
   check('Unconfigured failure is not replaced by setup success wording',preserve_error);app.close()
   app=App(browser)
   def form_contract():
    app.tab('settings');p=app.page
    p.locator('#certDescription').fill('Certificate & "notes"');p.locator('#certEmail').fill('owner@example.com')
    p.locator('#certDomains').fill('one.example.com\n*.example.com');p.locator('#certToken').fill('synthetic-not-a-token');p.locator('#def').check()
    before=p.locator('#certificateSettings').evaluate('e=>Array.from(new FormData(e).entries())')
    app.theme('light');after=p.locator('#certificateSettings').evaluate('e=>Array.from(new FormData(e).entries())')
    require(before==after,'theme changed submission values')
    values=dict(after);require(values['cert_desc']=='Certificate & "notes"' and values['domains']=='one.example.com\n*.example.com','rearranged fields changed values')
    require(values['default_on_create']=='1' and values['key_type']=='ec-384' and values['dns_sleep']=='60','field names or defaults changed')
    require(values['cf_token']=='synthetic-not-a-token' and values['auto_renew']=='1','credentials or renewal preference lost')
    require(not any(x.get('action') in ['save','apply','test','force','restore'] for x in app.posts),'theme submitted certificate action')
   check('Rearranged form keeps exact field names and values across theme switch',form_contract);app.close()
   app=App(browser,width=570,height=340)
   def short_log():
    app.tab('logs');app.page.locator('#mainContent').evaluate('e=>e.scrollTop=e.scrollHeight')
    r=app.rect('#fullLog');require(r['y']+r['height']<=340,'short window cannot reach log bottom')
    require(app.page.locator('#mainContent').evaluate('e=>e.scrollHeight>e.clientHeight'),'short viewport should have fallback scrolling')
   check('Very short Logs window permits reachable fallback page scrolling',short_log)
   def short_wizard():
    app.tab('dashboard');p=app.page;p.locator('#setupWizard-dashboard').click();p.wait_for_timeout(100)
    p.locator('#workflowViewLogs').click();p.locator('#workflowExit').scroll_into_view_if_needed()
    r=app.rect('#workflowExit');require(r['y']>=0 and r['y']+r['height']<=340,'short wizard exit cannot be reached')
   check('Very short wizard keeps Exit reachable with fallback scrolling',short_wizard);app.close()
   app=App(browser)
   def theme_state():
    app.tab('settings');app.page.locator('#certDescription').fill('Unsaved draft & punctuation');app.page.locator('#certToken').fill('synthetic-not-a-token')
    before=len(app.posts);app.theme('light');require(len(app.posts)==before,'theme posted request');require(app.page.locator('#certToken').input_value()=='synthetic-not-a-token','token lost');require(app.page.locator('#certDescription').input_value()=='Unsaved draft & punctuation','draft lost')
    app.reopen();require(app.page.locator('html').get_attribute('data-theme')=='light','palette not remembered');require(app.page.locator('.tabbtn.active').get_attribute('data-tab')=='settings','remembered tab lost')
   check('theme changes preserve draft and preference across simulated reopen; recent tab retained',theme_state)
   def log_behaviour():
    fit_log(app);app.page.locator('#fullLog').evaluate('e=>e.scrollTop=200');pos=app.page.locator('#fullLog').evaluate('e=>e.scrollTop');app.theme('dark');require(abs(app.page.locator('#fullLog').evaluate('e=>e.scrollTop')-pos)<1,'theme moved log')
    app.status['log']+='new line\n';app.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))");app.page.wait_for_timeout(90);require(abs(app.page.locator('#fullLog').evaluate('e=>e.scrollTop')-pos)<1,'poll stole reading position')
    app.page.locator('#pauseLog').click();text=app.page.locator('#fullLog').inner_text();app.status['log']='changed while paused';app.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))");app.page.wait_for_timeout(90);require(app.page.locator('#fullLog').inner_text()==text,'pause failed')
    app.page.locator('#logFilter').fill('0012');require('0012' in app.page.locator('#fullLog').inner_text(),'filter failed')
   check('log pause/filter and manual reading position retained across polls and theme',log_behaviour)
   app.close()
   for width,height in [(1320,780),(1188,708),(900,620),(768,680),(390,780)]:
    app=App(browser,width=width,height=height)
    for theme in ['dark','light']:
     app.theme(theme)
     for n in range(5):
      for logs in [False,True]:check(f'{width}x{height}:{theme}:wizard-{n+1}:logs={logs}',lambda n=n,logs=logs:wizard_step(app,n,logs))
     if width==1320:app.screenshot('wizard-log-'+theme)
     # Close actual wizard without actions, then theme button becomes available.
     app.page.locator('#workflowExit').click();app.page.wait_for_timeout(80)
    app.close()
   app=App(browser,blocked=True)
   check('storage blocked: theme remains functional',lambda:(app.theme('light'),require(app.page.locator('html').get_attribute('data-theme')=='light','failed theme'),require(not app.errors,repr(app.errors))))
   app.close()
   app=App(browser,theme='unrecognised')
   check('invalid saved palette falls back to dark',lambda:require(app.page.locator('html').get_attribute('data-theme')=='dark','bad preference accepted'));app.close()
   # Use real shared wizard entry and navigation with synthetic server receipts.
   app=App(browser)
   def actual_wizard():
    p=app.page;app.tab('settings');p.locator('#setupWizard-settings').click();p.locator('#workflowNext').click();p.locator('#wfDescription').fill('Uncommitted wizard draft');p.locator('#workflowNext').click()
    p.evaluate("window.requestScheduler=async()=>({ok:true,temporary:false,reused:true})")
    p.locator('#workflowStartWorker').click();p.wait_for_function("document.getElementById('workflowNext').hidden===false")
    p.locator('#workflowNext').click();require('Test and apply'==p.locator('#workflowHeading').inner_text(),'did not advance')
    p.locator('#workflowStage').click();p.wait_for_function("document.getElementById('workflowApply').disabled===false")
    require('Staging test succeeded' in p.locator('#workflowWizardStatus').inner_text(),'receipt not shown')
    # Theme storage event while modal open must not touch draft or eligibility.
    p.evaluate("window.dispatchEvent(new StorageEvent('storage',{key:'sadleracme.theme',newValue:'light'}))")
    require(p.locator('#wfDescription').input_value()=='Uncommitted wizard draft','theme changed wizard draft');require(not p.locator('#workflowApply').is_disabled(),'theme changed staging eligibility')
    p.locator('#workflowExit').click();p.wait_for_function("!document.getElementById('workflowModal').classList.contains('open')")
    require(app.config['cert_desc']=='SadlerACME Lab','draft was saved on exit');require(not any(x.get('action') in ['apply','force','wizard-apply','restore'] for x in app.posts),'unauthorised certificate action in fixture')
    require(not app.errors,repr(app.errors))
   check('actual wizard flow: staging receipt, palette event, safe exit without saving draft',actual_wizard)
   app.close();browser.close()
 finally:
  (R/'tests/RESULTS-1.0.0-1-browser.json').write_text(json.dumps(dict(scope='Local Chromium about:blank DOM/layout/JS; in-memory fetch and storage fixtures; no real DSM/ACME operations or native persistence claim',cases=results,failures=failures),indent=2)+'\n')
 print(f'{len(results)-len(failures)}/{len(results)} browser checks passed; {len(failures)} failures.')
 raise SystemExit(bool(failures))
