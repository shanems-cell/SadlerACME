/* Offline DOM/DSM fixtures. These exercise workflow boundaries, not actual DSM APIs. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/workflow.js'), 'utf8');
const helpers = require('../src/ui/workflow.js');
const initial = {email:'owner@example.com',domains:['example.com','*.example.com'],key_type:'ec-384',cert_desc:'Certificate',default_on_create:'0',auto_renew:'1',dns_sleep:'60'};
const fixtureToken = 'fixture_cloudflare_token_12345';
const backup = {format:'SadlerACME',version:1,created_at:'2026-09-27T00:00:00Z',settings:{...initial,auto_renew:'0'},certificate:null,acme_account_key:null,metadata:{domains:[],key_type:''}};

function match(node, selector) {
  const parts = selector.trim().split(/\s+/);
  const last = parts.pop();
  const id = /#([\w-]+)/.exec(last), cls = /\.([\w-]+)/.exec(last), tag = /^[a-zA-Z][\w-]*/.exec(last);
  if (id && node.id !== id[1] || cls && !node.classList.contains(cls[1]) || tag && node.tagName !== tag[0].toUpperCase()) return false;
  const attrs = [...last.matchAll(/\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]/g)];
  if (attrs.some(a => !(a[1] in node.attributes) || a[2] !== undefined && node.attributes[a[1]] !== a[2])) return false;
  if (!parts.length) return true;
  for (let parent=node.parentNode; parent; parent=parent.parentNode) if (match(parent,parts.join(' '))) return true;
  return false;
}
function fixture(options={}) {
  const nodes = new Map(), requests = [], bridge = [], modes = [], events = {}, receipts = new Map();
  let config = JSON.parse(JSON.stringify(options.config || initial)), hasToken = options.hasToken !== false, failAction = '', deferAction = '', failSaveAuto = false, transportFailure = '', rejectAction = '', rejectionCode = 'worker_unavailable', counter = 0, hash = 'fixture-hash';
  const currentStatus = {package_running:'yes',worker_available:'yes',queue_state:'active',scheduler_status:'Installed and enabled',setup_temporary:'no',uninstall_ready:'no',state:'idle',message:'Ready',last_run:'now',local_cert_available:'yes',dsm_match:'yes',dsm_id:'existing-id',restore_requires_issue:'no'};
  class Node {
    constructor(tag='div') { this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;this.attributes={};this.handlers={};this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.readOnly=false;this.checked=false;this.files=[];this.className='';this.type='';this.name='';this.id=''; }
    get classList(){const self=this; return {add(v){const set=new Set(self.className.split(/\s+/));set.add(v);self.className=[...set].join(' ');},remove(v){self.className=self.className.split(/\s+/).filter(c=>c!==v).join(' ');},contains(v){return self.className.split(/\s+/).includes(v);},toggle(v,force){const has=self.className.split(/\s+/).includes(v);const add=force===undefined?!has:force;if(add)this.add(v);else this.remove(v);return add;}};}
    setAttribute(k,v){this.attributes[k]=String(v);if(['id','name','type','value','class'].includes(k)){this[k==='class'?'className':k]=String(v);}if(k==='id')nodes.set(v,this);}
    getAttribute(k){return this.attributes[k] || null;}
    appendChild(node){node.parentNode=this;this.children.push(node);if(node.id)nodes.set(node.id,node);return node;}
    insertBefore(node,before){node.parentNode=this;const i=before==null?this.children.length:this.children.indexOf(before);this.children.splice(i<0?0:i,0,node);return node;}
    get firstChild(){return this.children[0] || null;}
    get nextSibling(){if(!this.parentNode)return null;return this.parentNode.children[this.parentNode.children.indexOf(this)+1] || null;}
    remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);}
    addEventListener(type, fn){(this.handlers[type] ||= []).push(fn);}
    dispatch(type){if(this.disabled && type==='click')return;return Promise.all((this.handlers[type]||[]).map(fn=>fn.call(this,{preventDefault(){},target:this})));}
    click(){return this.dispatch('click');}
    focus(){document.activeElement=this;}
    get offsetParent(){for(let n=this;n;n=n.parentNode)if(n.hidden)return null;return this.parentNode;}
    querySelectorAll(selector){const found=[];function visit(node){for(const child of node.children){if(selector.split(',').some(s=>match(child,s)))found.push(child);visit(child);}}visit(this);return found;}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    set innerHTML(html){this.children=[];const stack=[this];for(const m of html.matchAll(/<\/?[a-zA-Z][^>]*>/g)){const token=m[0];if(token.startsWith('</')){if(stack.length>1)stack.pop();continue;}const tag=/^<([\w-]+)/.exec(token)[1];const node=new Node(tag);for(const a of token.matchAll(/([\w-]+)(?:="([^"]*)")?/g)){if(a.index===1)continue;node.setAttribute(a[1],a[2]||'');if(a[1]==='hidden')node.hidden=true;if(a[1]==='checked')node.checked=true;if(a[1]==='disabled')node.disabled=true;}stack[stack.length-1].appendChild(node);if(!['input','br','hr','img','meta','link'].includes(tag))stack.push(node);}}
  }
  const body = new Node('body');
  const document = {body,activeElement:null,readyState:'complete',createElement:t=>new Node(t),getElementById:id=>nodes.get(id)||null,querySelectorAll:s=>body.querySelectorAll(s),querySelector:s=>body.querySelector(s),addEventListener(){}};
  body.innerHTML = '<div id="tab-dashboard"><div class="page-heading"><div class="wizard-heading-actions"></div></div></div><div id="tab-settings"><div id="settingsHeading" class="page-heading"><div class="wizard-heading-actions"></div></div><form id="certificateSettings"><input name="csrf" value="fixture-csrf"><input name="email"><textarea name="domains"></textarea><select name="key_type"></select><input name="cert_desc"><input name="cf_token"><input name="dns_sleep"></form><div id="certificateOperations"></div></div><div id="tab-backup"></div><div id="tab-uninstall"></div><input id="auto" name="auto_renew" type="checkbox" form="certificateSettings"><button class="tabbtn" data-tab="backup"></button><button class="tabbtn" data-tab="uninstall"></button><button class="tabbtn" data-tab="logs"></button>';
  // Model the summaries rendered by index.cgi before the wizard opens.
  for (const [id,value] of Object.entries({configuredDescription:config.cert_desc,configuredDomains:config.domains.join('\n'),configuredKey:'ECC P-384',configuredToken:'Token configured: '+(hasToken?'Yes':'No')})) {
    const cell=new Node();cell.setAttribute('id',id);cell.textContent=value;body.appendChild(cell);
  }
  const parent = {postMessage(data,origin){bridge.push({data,origin});}};
  const context = {document,URL,URLSearchParams,Blob,TextEncoder,Promise,Date,Math,Array,Object,Error,console,window:null,globalThis:null};
  context.window=context;context.globalThis=context;context.parent=parent;context.location={href:'https://nas.invalid/webman/3rdparty/sadleracme/index.cgi?SynoToken=fixture-session',origin:'https://nas.invalid'};
  context.setTimeout=(fn,ms)=>ms<5000?setTimeout(fn,0):1;context.clearTimeout=id=>clearTimeout(id);context.confirm=()=>true;context.alert=()=>{};
  context.addEventListener=(name,fn)=>(events[name]||=[]).push(fn);
  context.fetch=async(url,options={})=>{
    const u=new URL(url), fields=options.body?JSON.parse(options.body):null;requests.push({url:u,options,fields});
    assert.equal(u.searchParams.get('SynoToken'),'fixture-session','DSM token must survive every workflow request');
    const reply = value=>({ok:true,status:200,json:async()=>value});
    if(u.searchParams.get('api')==='settings')return reply({ok:true,config:JSON.parse(JSON.stringify(config)),has_token:hasToken,settings_hash:hash});
    if(u.searchParams.get('api')==='status')return reply({...currentStatus});
    if(u.searchParams.get('api')==='job')return reply(receipts.get(u.searchParams.get('id')) || {ok:true,job_id:u.searchParams.get('id'),result:'pending'});
    assert.equal(fields.csrf,'fixture-csrf');
    if(fields.action==='automation-intent')return reply({ok:true});
    if(fields.action==='save-auto'){
      if(failSaveAuto)return{ok:false,status:409,json:async()=>({ok:false,message:'Fixture settings changed'})};
      config.auto_renew=fields.auto_renew;hash+='a';return reply({ok:true});
    }
    if(fields.action===rejectAction)return{ok:false,status:409,json:async()=>({ok:false,code:rejectionCode,message:'Fixture request rejected'})};
    const id='fixture-job-'+(++counter), failed=fields.action===failAction;
    receipts.set(id,{ok:true,job_id:id,result:fields.action===deferAction?'pending':failed?'failed':'completed',message:failed?'Fixture operation failed':'Completed'});
    // Deliberately put another action in global last_job: durable receipt must win.
    currentStatus.last_job='unrelated-refresh';currentStatus.last_job_result='completed';
    if(!failed && fields.action==='wizard-apply'){config={...fields.config};hasToken=hasToken || !!config.cf_token;delete config.cf_token;hash+='x';}
    if(!failed && fields.action==='restore'){config={...fields.backup.settings,auto_renew:'0'};hasToken=true;hash+='r';currentStatus.restore_requires_issue='yes';}
    if(!failed && fields.action==='cancel-setup')currentStatus.setup_temporary='no';
    if(!failed && fields.action==='prepare-uninstall')currentStatus.uninstall_ready='yes';
    if(fields.action===transportFailure)throw new Error('Fixture response lost after server accepted operation');
    return reply({ok:true,job_id:id,message:'Queued'});
  };
  vm.runInNewContext(options.source || source,context,{filename:'workflow.js'});
  const realScheduler=context.requestScheduler;
  context.requestScheduler=async mode=>{modes.push(mode);if(mode==='setup')currentStatus.worker_available='yes';return{ok:true,temporary:false,reused:true};};
  const flush=async()=>{for(let i=0;i<15;i++)await new Promise(setImmediate);};
  const click=async id=>{await nodes.get(id).click();await flush();};
  return {context,nodes,requests,bridge,modes,events,currentStatus,flush,click,realScheduler,get config(){return config;},set failAction(v){failAction=v;},set rejectAction(v){rejectAction=v;},set rejectionCode(v){rejectionCode=v;},set deferAction(v){deferAction=v;},set failSaveAuto(v){failSaveAuto=v;},completePending(result){for(const receipt of receipts.values())if(receipt.result==='pending'){receipt.result=result;receipt.message=result==='completed'?'Completed':'DSM scheduler remained busy after waiting';}},set transportFailure(v){transportFailure=v;},async open(value){await context.SadlerWorkflow.openWizard(value);await flush();},sendBridge(data,origin=context.location.origin,source=parent){for(const fn of events.message||[])fn({origin,source,data});}};
}

async function runSuite(){
  const safe=helpers.cleanConfig({...initial,cf_token:fixtureToken,unexpected:'secret'});
  assert.equal(safe.cf_token,'');assert(!('unexpected' in safe));safe.domains.push('new.example.com');assert.equal(initial.domains.length,2);
  assert.deepEqual(helpers.domainsFromText('EXAMPLE.com, *.example.com\nexample.com'),['example.com','*.example.com']);
  assert.throws(()=>helpers.validateConfig({...safe,cf_token:''},false),/token/);
  assert.throws(()=>helpers.validateConfig({...safe,domains:['bad;command'],cf_token:fixtureToken},false),/DNS/);
  assert.throws(()=>helpers.validateConfig({...safe,dns_sleep:'1',cf_token:fixtureToken},false),/30/);
  for(const email of ["o'wner@example.com",'a`b@example.com','a$(cmd)@example.com'])assert.throws(()=>helpers.validateConfig({...safe,email,cf_token:fixtureToken},false),/email/);
  assert.equal(helpers.previewBackup(JSON.stringify(backup)).format,'SadlerACME');
  assert.throws(()=>helpers.previewBackup(JSON.stringify({...backup,settings:{...initial,cf_token:fixtureToken}})),/unexpectedly/);
  assert.throws(()=>helpers.previewBackup('x'.repeat(524289)),/too large/);
  assert.equal(helpers.jobOutcome({last_job:'different',last_job_result:'completed'},'wanted'),null);

  async function workerStep(f) { await f.open(); await f.click('workflowNext'); await f.click('workflowNext'); }
  const startupFailure=fixture();startupFailure.currentStatus.queue_state='inactive';
  startupFailure.context.requestScheduler=async mode=>{startupFailure.modes.push(mode);Object.assign(startupFailure.currentStatus,{state:'error',last_action:'migration',last_run:'new-attempt',message:'Legacy certificate source cannot be verified safely.'});return{ok:true,temporary:true,created:true};};
  await workerStep(startupFailure);await startupFailure.click('workflowStartWorker');
  assert.match(startupFailure.nodes.get('workflowWizardStatus').textContent,/Background processing could not start: Legacy certificate source/,'A new initialization error appears immediately');
  assert.equal(startupFailure.nodes.get('workflowNext').hidden,true,'Failed initialization cannot advance setup');
  assert(!startupFailure.requests.some(r=>r.fields&&r.fields.action==='scheduler-status'),'Do not queue a readiness check after a known startup failure');

  const staleFailure=fixture();Object.assign(staleFailure.currentStatus,{state:'error',last_action:'migration',last_run:'earlier-attempt',message:'Earlier migration failed'});
  await workerStep(staleFailure);await staleFailure.click('workflowStartWorker');
  assert.match(staleFailure.nodes.get('workflowWizardStatus').textContent,/Existing permanent automation was reused/,'A stale error must not reject a successful permanent-worker readiness receipt');
  assert.equal(staleFailure.requests.filter(r=>r.fields&&r.fields.action==='scheduler-status').length,1,'Each startup uses exactly one correlated readiness check');

  const repeatedFailure=fixture();Object.assign(repeatedFailure.currentStatus,{queue_state:'inactive',state:'error',last_action:'migration',last_run:'earlier-attempt',message:'Migration blocked'});
  repeatedFailure.context.requestScheduler=async()=>{repeatedFailure.currentStatus.last_run='new-attempt';return{ok:true};};
  await workerStep(repeatedFailure);await repeatedFailure.click('workflowStartWorker');
  assert.match(repeatedFailure.nodes.get('workflowWizardStatus').textContent,/Background processing could not start: Migration blocked/,'A newly dated repetition of an earlier error is reported');

  const cachedQueue=fixture();cachedQueue.deferAction='scheduler-status';await workerStep(cachedQueue);await cachedQueue.click('workflowStartWorker');
  assert.equal(cachedQueue.nodes.get('workflowNext').hidden,true,'Cached active queue cannot prove readiness');
  assert.match(cachedQueue.nodes.get('workflowWizardStatus').textContent,/Waiting for the SadlerACME worker/);
  Object.assign(cachedQueue.currentStatus,{state:'error',last_action:'setup',last_run:'new-attempt',message:'Unable to start the temporary queue watcher'});
  await new Promise(resolve=>setTimeout(resolve,10));await cachedQueue.flush();
  assert.match(cachedQueue.nodes.get('workflowWizardStatus').textContent,/Background processing could not start: Unable to start/,'New startup errors remain visible while a cached queue probe is pending');
  assert.equal(cachedQueue.requests.filter(r=>r.fields&&r.fields.action==='scheduler-status').length,1,'Polling never enqueues repeated readiness probes');

  const delayedReady=fixture();delayedReady.deferAction='scheduler-status';await workerStep(delayedReady);await delayedReady.click('workflowStartWorker');
  assert.equal(delayedReady.nodes.get('workflowNext').hidden,true);
  delayedReady.completePending('completed');await new Promise(resolve=>setTimeout(resolve,10));await delayedReady.flush();
  assert.match(delayedReady.nodes.get('workflowWizardStatus').textContent,/Worker is ready/,'A delayed matching receipt confirms readiness');
  assert.equal(delayedReady.nodes.get('workflowNext').hidden,false);

  const unrelatedFailure=fixture();unrelatedFailure.deferAction='scheduler-status';await workerStep(unrelatedFailure);await unrelatedFailure.click('workflowStartWorker');
  Object.assign(unrelatedFailure.currentStatus,{state:'error',last_action:'restore',last_run:'another-operation',message:'Unrelated restore failed'});
  await new Promise(resolve=>setTimeout(resolve,10));await unrelatedFailure.flush();
  assert.match(unrelatedFailure.nodes.get('workflowWizardStatus').textContent,/Waiting for the SadlerACME worker/,'An unrelated operation error is not a startup failure');
  Object.assign(unrelatedFailure.currentStatus,{last_action:'worker',active_job:'another-job'});
  await new Promise(resolve=>setTimeout(resolve,10));await unrelatedFailure.flush();
  assert.match(unrelatedFailure.nodes.get('workflowWizardStatus').textContent,/Waiting for the SadlerACME worker/,'Another active worker job must use its own receipt');
  unrelatedFailure.completePending('completed');await new Promise(resolve=>setTimeout(resolve,10));await unrelatedFailure.flush();
  assert.match(unrelatedFailure.nodes.get('workflowWizardStatus').textContent,/Worker is ready/);

  const startupTimeout=fixture();let startupClock=1000;startupTimeout.context.Date=class extends Date {static now(){return startupClock;}};
  startupTimeout.deferAction='scheduler-status';await workerStep(startupTimeout);await startupTimeout.click('workflowStartWorker');
  startupClock+=90001;await new Promise(resolve=>setTimeout(resolve,10));await startupTimeout.flush();
  assert.match(startupTimeout.nodes.get('workflowWizardStatus').textContent,/worker did not confirm readiness/,'An unprocessed readiness probe times out after the startup limit');
  assert.equal(startupTimeout.nodes.get('workflowNext').hidden,true);

  const failedProbe=fixture();failedProbe.failAction='scheduler-status';await workerStep(failedProbe);await failedProbe.click('workflowStartWorker');
  assert.match(failedProbe.nodes.get('workflowWizardStatus').textContent,/Fixture operation failed/,'A failed readiness receipt supplies the actual error');
  assert.equal(failedProbe.nodes.get('workflowNext').hidden,true);

  const transientRead=fixture(), transientFetch=transientRead.context.fetch;
  let transientArmed=false;const transientFailures=['status','job'];
  transientRead.context.requestScheduler=async()=>{transientArmed=true;return{ok:true};};
  transientRead.context.fetch=async(url,options)=>{if(transientArmed&&new URL(url).searchParams.get('api')===transientFailures[0]){transientFailures.shift();throw new Error('Temporary status connection failure');}return transientFetch(url,options);};
  await workerStep(transientRead);await transientRead.click('workflowStartWorker');await new Promise(resolve=>setTimeout(resolve,15));await transientRead.flush();
  assert.equal(transientFailures.length,0,'Both status and receipt transient failures were exercised');
  assert.match(transientRead.nodes.get('workflowWizardStatus').textContent,/Worker is ready/,'Transient GET failures recover during startup');
  assert.equal(transientRead.requests.filter(r=>r.fields&&r.fields.action==='scheduler-status').length,1,'Read retries never replay the readiness probe POST');

  const persistentRead=fixture(), persistentFetch=persistentRead.context.fetch;
  let persistentArmed=false,persistentFailures=0;
  persistentRead.context.requestScheduler=async()=>{persistentArmed=true;return{ok:true};};
  persistentRead.context.fetch=async(url,options)=>{if(persistentArmed&&new URL(url).searchParams.get('api')==='status'){persistentFailures++;throw new Error('Persistent status connection failure');}return persistentFetch(url,options);};
  await workerStep(persistentRead);await persistentRead.click('workflowStartWorker');await new Promise(resolve=>setTimeout(resolve,15));await persistentRead.flush();
  assert.equal(persistentFailures,4,'Persistent GET failures stop after four attempts');
  assert.match(persistentRead.nodes.get('workflowWizardStatus').textContent,/Persistent status connection failure/);
  assert.equal(persistentRead.nodes.get('workflowNext').hidden,true);

  const lostProbe=fixture();lostProbe.transportFailure='scheduler-status';await workerStep(lostProbe);await lostProbe.click('workflowStartWorker');
  assert.match(lostProbe.nodes.get('workflowWizardStatus').textContent,/Fixture response lost after server accepted operation/,'A probe POST failure is not retried as a read');
  assert.equal(lostProbe.requests.filter(r=>r.fields&&r.fields.action==='scheduler-status').length,1);

  const fileFor=value=>{const text=JSON.stringify(value);return{size:Buffer.byteLength(text),text:async()=>text};};
  const selectFile=async(f,file)=>{const picker=f.nodes.get('workflowRestoreFile');picker.files=file?[file]:[];picker.value=file?'fixture.json':'';await picker.dispatch('change');await f.flush();};
  const preview=fixture(), restoreCard=preview.nodes.get('workflowRestoreCard');
  assert.equal(preview.nodes.get('tab-settings').firstChild,preview.nodes.get('settingsHeading'),'The page heading stays above the setup launcher');
  assert(preview.nodes.get('settingsHeading').querySelector('#setupWizard-settings'),'Settings wizard entry lives in the heading');
  assert(preview.nodes.get('tab-dashboard').querySelector('#setupWizard-dashboard'),'Dashboard shares the same wizard');
  assert.equal(preview.context.document.querySelectorAll('.workflow-intro').length,0,'No duplicate wizard introduction card');
  assert.equal(preview.nodes.get('certificateOperations').querySelector('#workflowLastOperation'),preview.nodes.get('workflowLastOperation'),'Operation feedback stays with certificate actions');
  for(const id of ['workflowDownload','workflowRestoreButton'])assert.equal(preview.nodes.get('tab-backup').querySelector('#'+id),preview.nodes.get(id),'Backup and restore actions are on Backup & Restore');
  for(const id of ['workflowPrepare','workflowBackupSaved','workflowBackupSkip','workflowRecoveryLink']){
    assert.equal(preview.nodes.get('tab-uninstall').querySelector('#'+id),preview.nodes.get(id),'Preparation, acknowledgement and recovery share Uninstall');
    assert.equal(preview.nodes.get('tab-backup').querySelector('#'+id),null,'Removal controls do not appear on Backup & Restore');
  }
  assert.equal(restoreCard.querySelector('input[type="file"]'),null,'Restore card contains only the wizard launcher');
  assert.equal(preview.context.document.querySelectorAll('input[type="file"]').length,1,'Exactly one recovery file picker exists');
  assert.equal(preview.nodes.get('workflowRestoreButton').disabled,false,'Restore launcher needs no outside selection');
  for(const action of ['Download','Restore','Prepare'])assert.equal(preview.nodes.get('workflow'+action+'Card').querySelector('#workflow'+action+'Status'),preview.nodes.get('workflow'+action+'Status'),'Each status stays beside its action');
  const beforeRestoreRequests=preview.requests.length;
  preview.nodes.get('workflowRestoreButton').focus();await preview.click('workflowRestoreButton');
  assert.equal(preview.nodes.get('workflowModal').classList.contains('open'),true);
  assert.equal(preview.nodes.get('workflowHeading').textContent,'Choose setup');
  assert.equal(preview.nodes.get('workflowRestore').checked,true);
  assert.equal(preview.nodes.get('workflowRestoreFileWrap').hidden,false);
  assert(!preview.requests.slice(beforeRestoreRequests).some(r=>r.fields),'Restore Backup only opens the review wizard');
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/Choose a recovery file/);
  await preview.click('workflowNext');assert.match(preview.nodes.get('workflowWizardStatus').textContent,/Choose a recovery backup/);
  await selectFile(preview,fileFor(backup));
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/Created:.*2026-09-27/);
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/Domains: example.com, \*\.example.com/);
  await preview.click('workflowNext');assert.equal(preview.nodes.get('wfDomains').value,initial.domains.join('\n'),'One selected backup populates the wizard');
  await preview.click('workflowBack');await preview.click('workflowExit');
  assert.equal(preview.nodes.get('workflowRestoreFile').value,'');
  assert.equal(preview.context.document.activeElement,preview.nodes.get('workflowRestoreButton'),'Exit returns focus to the Restore launcher');
  await preview.click('workflowRestoreButton');
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/Choose a recovery file/,'Reopening clears the old backup');
  await selectFile(preview,fileFor(backup));await selectFile(preview,{size:8,text:async()=>'{invalid'});
  assert(preview.nodes.get('workflowWizardStatus').classList.contains('error'));
  assert.match(preview.nodes.get('workflowWizardStatus').textContent,/valid SadlerACME JSON/);
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/Choose a recovery file/);
  assert.equal(preview.nodes.get('workflowRestoreFile').value,'');
  await preview.click('workflowNext');assert.match(preview.nodes.get('workflowWizardStatus').textContent,/Choose a recovery backup/,'An invalid file cannot leave a previous backup selected');
  await selectFile(preview,{size:524289,text:async()=>{throw new Error('Oversized file must not be read');}});
  assert.match(preview.nodes.get('workflowWizardStatus').textContent,/too large/);
  await selectFile(preview,{size:20,text:async()=>{throw new Error('Fixture file read failed');}});
  assert.match(preview.nodes.get('workflowWizardStatus').textContent,/Fixture file read failed/);
  await selectFile(preview,fileFor({...backup,created_at:'<img src=x onerror=alert(1)>'}));
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/<img src=x onerror=alert\(1\)>/,'Untrusted preview text remains literal');
  assert.equal(preview.nodes.get('workflowBackupPreview').children.length,0);
  await preview.nodes.get('workflowRestoreFile').dispatch('cancel');
  assert.match(preview.nodes.get('workflowBackupPreview').textContent,/Choose a recovery file/);
  await preview.click('workflowNext');assert.equal(preview.nodes.get('workflowHeading').textContent,'Choose setup');
  await selectFile(preview,fileFor(backup));await selectFile(preview,null);
  await preview.click('workflowNext');assert.equal(preview.nodes.get('workflowHeading').textContent,'Choose setup','Clearing the picker resets selection');

  const race=fixture();await race.click('workflowRestoreButton');let finishOldRead;
  race.nodes.get('workflowRestoreFile').files=[{size:100,text:()=>new Promise(resolve=>{finishOldRead=resolve;})}];
  const oldRead=race.nodes.get('workflowRestoreFile').dispatch('change');await race.flush();
  assert.equal(race.nodes.get('workflowNext').disabled,true,'Cannot advance while backup is being read');
  assert.equal(race.nodes.get('workflowRestoreFile').disabled,false,'A pending file read can be replaced');
  await selectFile(race,fileFor({...backup,settings:{...backup.settings,domains:['new.example.com']}}));
  finishOldRead(JSON.stringify(backup));await oldRead;await race.flush();
  assert.match(race.nodes.get('workflowBackupPreview').textContent,/Domains: new.example.com/,'Late file read cannot replace newer preview');
  await race.click('workflowNext');assert.equal(race.nodes.get('wfDomains').value,'new.example.com','Restore uses the latest file');
  await race.click('workflowBack');
  let rejectCancelledRead;
  race.nodes.get('workflowRestoreFile').files=[{size:100,text:()=>new Promise((_,reject)=>{rejectCancelledRead=reject;})}];
  const cancelledRead=race.nodes.get('workflowRestoreFile').dispatch('change');await race.flush();
  await race.nodes.get('workflowRestoreFile').dispatch('cancel');
  rejectCancelledRead(new Error('Late cancelled file error'));await cancelledRead;await race.flush();
  assert.equal(race.nodes.get('workflowWizardStatus').textContent,'','Cancelled read cannot publish a stale error');
  let finishClosedRead;
  race.nodes.get('workflowRestoreFile').files=[{size:100,text:()=>new Promise(resolve=>{finishClosedRead=resolve;})}];
  const closedRead=race.nodes.get('workflowRestoreFile').dispatch('change');await race.flush();await race.click('workflowExit');
  await race.click('workflowRestoreButton');finishClosedRead(JSON.stringify(backup));await closedRead;await race.flush();
  assert.match(race.nodes.get('workflowBackupPreview').textContent,/Choose a recovery file/,'An exited wizard cannot populate a later wizard');
  let finishModeRead;
  race.nodes.get('workflowRestoreFile').files=[{size:100,text:()=>new Promise(resolve=>{finishModeRead=resolve;})}];
  const modeRead=race.nodes.get('workflowRestoreFile').dispatch('change');await race.flush();
  race.nodes.get('workflowNew').checked=true;await race.nodes.get('workflowNew').dispatch('change');await race.flush();
  finishModeRead(JSON.stringify(backup));await modeRead;await race.flush();
  assert.equal(race.nodes.get('workflowRestoreFileWrap').hidden,true,'Switching setup mode invalidates pending backup reads');
  assert.equal(race.nodes.get('workflowAutoRenew').checked,true);

  const busyPanel=fixture();busyPanel.deferAction='backup';const pendingDownload=busyPanel.nodes.get('workflowDownload').dispatch('click');await busyPanel.flush();
  assert.equal(busyPanel.nodes.get('workflowRestoreButton').disabled,true,'Another operation blocks the Restore launcher');
  assert.equal(busyPanel.nodes.get('workflowPrepare').disabled,true,'A backup also blocks preparation on the separate Uninstall page');
  for(const id of ['workflowBackupSaved','workflowBackupSkip'])assert.equal(busyPanel.nodes.get(id).disabled,true,'Preparation acknowledgement stays fixed while another operation runs');
  let backupVisits=0;busyPanel.context.document.querySelector('.tabbtn[data-tab="backup"]').addEventListener('click',()=>{backupVisits++;});
  assert.equal(busyPanel.nodes.get('workflowGoToBackup').disabled,false,'The backup navigation link remains available during work');
  await busyPanel.click('workflowGoToBackup');
  assert.equal(backupVisits,1,'The optional backup link activates Backup & Restore');
  assert.equal(busyPanel.requests.filter(r=>r.fields&&r.fields.action==='backup').length,1,'Navigation does not restart the pending backup');
  assert.equal(busyPanel.nodes.get('workflowRestoreButton').disabled,true,'Navigation preserves the pending operation guard');
  let logVisits=0;const logScrolls=[];busyPanel.context.scrollTo=(x,y)=>logScrolls.push([x,y]);busyPanel.context.document.querySelector('.tabbtn[data-tab="logs"]').addEventListener('click',()=>{logVisits++;});
  for(const id of ['workflowDownloadLogs','workflowRestoreLogs','workflowPrepareLogs']){assert.equal(busyPanel.nodes.get(id).disabled,false);await busyPanel.click(id);}
  assert.equal(logVisits,3,'View Logs navigates while work is pending');
  assert.deepEqual(logScrolls,[[0,0],[0,0],[0,0]]);
  busyPanel.completePending('failed');await pendingDownload;await busyPanel.flush();
  assert.equal(busyPanel.nodes.get('workflowRestoreButton').disabled,false);
  assert.equal(busyPanel.nodes.get('workflowPrepare').disabled,false,'Preparation is re-enabled when the backup finishes');
  for(const id of ['workflowBackupSaved','workflowBackupSkip'])assert.equal(busyPanel.nodes.get(id).disabled,false,'Preparation acknowledgement is available after the operation finishes');
  assert.equal(busyPanel.nodes.get('workflowRestoreStatus').textContent,'','Download feedback stays separate from restore feedback');
  assert(busyPanel.nodes.get('workflowDownloadStatus').classList.contains('error'));

  const countAction=(f,action)=>f.requests.filter(r=>r.fields&&r.fields.action===action).length;
  function temporaryWorker(f) {
    f.context.requestScheduler=async mode=>{f.modes.push(mode);if(mode==='setup'){Object.assign(f.currentStatus,{worker_available:'yes',setup_temporary:'yes',setup_expires_epoch:'12345'});return{ok:true,temporary:true,created:true};}return{ok:true};};
  }
  async function restoreStep(f) {
    await f.click('workflowRestoreButton');await selectFile(f,fileFor(backup));await f.click('workflowNext');
    f.nodes.get('wfToken').value=fixtureToken;await f.click('workflowNext');await f.click('workflowStartWorker');await f.click('workflowNext');
  }
  const expired=fixture();temporaryWorker(expired);await restoreStep(expired);
  Object.assign(expired.currentStatus,{worker_available:'no',setup_temporary:'no',setup_expires_epoch:''});
  await expired.context.SadlerWorkflow.refresh();await expired.flush();
  assert.match(expired.nodes.get('workflowWorkerStatus').textContent,/one-hour setup session may have expired/,'Known temporary context survives cleared public lease data');
  assert.equal(expired.nodes.get('workflowWorkerReady').hidden,true,'Fresh queue availability revokes stale worker readiness');
  assert.equal(expired.nodes.get('workflowStartWorker').textContent,'Restart Worker');
  assert.equal(expired.nodes.get('workflowStartWorker').offsetParent!==null,true,'Restart is available on restore review');
  assert.equal(expired.nodes.get('workflowRestoreRun').disabled,true,'Unavailable worker must be restarted before explicit restore');
  assert.equal(expired.nodes.get('workflowBack').disabled,false,'Known unavailable worker does not lock Back');
  await expired.click('workflowBack');await expired.click('workflowBack');
  assert.equal(expired.nodes.get('wfToken').value,fixtureToken,'Back retains Cloudflare token in the open draft');
  await expired.click('workflowNext');
  expired.context.requestScheduler=expired.realScheduler;await expired.click('workflowStartWorker');
  expired.sendBridge({type:'sadleracme.scheduler.result',requestId:expired.bridge[0].data.requestId,ok:false,needsPassword:true,message:'Confirm restart'});await expired.flush();
  expired.nodes.get('workflowPassword').value='cancelled-password';await expired.click('workflowPasswordCancel');
  assert.match(expired.nodes.get('workflowWizardStatus').textContent,/confirmation cancelled.*progress has been kept/);
  assert.equal(expired.nodes.get('workflowPassword').value,'');
  assert.equal(expired.nodes.get('wfToken').value,fixtureToken);
  assert.equal(expired.nodes.get('workflowStartWorker').disabled,false,'Password cancellation allows another explicit restart');
  assert.equal(countAction(expired,'restore'),0,'Cancel does not queue the original operation');
  temporaryWorker(expired);await expired.click('workflowStartWorker');await expired.click('workflowNext');
  assert.equal(expired.nodes.get('workflowRestoreRun').disabled,false);
  assert.equal(countAction(expired,'restore'),0,'Successful restart never replays the rejected or pending operation');
  await expired.click('workflowRestoreRun');
  const restoredRequest=expired.requests.find(r=>r.fields&&r.fields.action==='restore').fields;
  assert.deepEqual(restoredRequest.backup,backup,'The originally selected backup survives restart');
  assert.equal(restoredRequest.config.cf_token,fixtureToken);
  assert.equal(restoredRequest.expected_settings_hash,'fixture-hash','Restart does not replace the draft hash');
  assert.equal(countAction(expired,'restore'),1);
  assert(!expired.requests.some(r=>r.options.body&&r.options.body.includes('cancelled-password')),'Cancelled DSM password is never submitted to CGI');

  const admissionRace=fixture();temporaryWorker(admissionRace);await restoreStep(admissionRace);
  admissionRace.rejectAction='restore';await admissionRace.click('workflowRestoreRun');
  assert.match(admissionRace.nodes.get('workflowWizardStatus').textContent,/may have expired.*This request was not queued/,'Typed queue rejection gives actionable guidance');
  assert.equal(admissionRace.nodes.get('workflowStartWorker').disabled,false);
  assert.equal(admissionRace.nodes.get('workflowBack').disabled,false);
  assert.deepEqual(admissionRace.config,initial,'Pre-queue rejection cannot change saved settings');
  admissionRace.rejectAction='';await admissionRace.click('workflowStartWorker');
  assert.equal(countAction(admissionRace,'restore'),1,'Readiness recovery does not submit restore again');
  await admissionRace.click('workflowRestoreRun');assert.equal(countAction(admissionRace,'restore'),2,'Restore retries only on user click');
  assert.equal(admissionRace.nodes.get('workflowBack').hidden,true,'Committed restore keeps its commit guard');
  Object.assign(admissionRace.currentStatus,{worker_available:'no',setup_temporary:'no'});await admissionRace.context.SadlerWorkflow.refresh();
  assert.equal(admissionRace.nodes.get('workflowStartWorker').offsetParent!==null,true,'Committed restore can restart without Back');
  await admissionRace.click('workflowContinueApplied');
  assert.equal(admissionRace.nodes.get('workflowStartWorker').offsetParent!==null,true,'Finish retains recovery access');
  assert.equal(admissionRace.nodes.get('workflowFinish').disabled,true);
  await admissionRace.click('workflowStartWorker');assert.equal(admissionRace.nodes.get('workflowFinish').disabled,false);
  assert.equal(countAction(admissionRace,'restore'),2,'Committed recovery never restores twice');
  admissionRace.rejectAction='finish-setup';await admissionRace.click('workflowFinish');
  assert.match(admissionRace.nodes.get('workflowWizardStatus').textContent,/This request was not queued/);
  assert.equal(admissionRace.nodes.get('workflowStartWorker').disabled,false,'Finish admission rejection permits explicit recovery');
  admissionRace.rejectAction='';await admissionRace.click('workflowStartWorker');
  assert.equal(countAction(admissionRace,'finish-setup'),1,'Restart never repeats Finish');
  await admissionRace.click('workflowFinish');assert.equal(admissionRace.nodes.get('workflowExit').textContent,'Close');
  assert.equal(countAction(admissionRace,'restore'),2);

  const expiredApply=fixture();temporaryWorker(expiredApply);await workerStep(expiredApply);await expiredApply.click('workflowStartWorker');await expiredApply.click('workflowNext');await expiredApply.click('workflowStage');
  expiredApply.rejectAction='wizard-apply';await expiredApply.click('workflowApply');
  assert.equal(expiredApply.nodes.get('workflowApply').disabled,true);
  expiredApply.rejectAction='';await expiredApply.click('workflowStartWorker');
  assert.equal(expiredApply.nodes.get('workflowApply').disabled,false,'Successful staging remains valid after unavailable queue recovery');
  assert.equal(countAction(expiredApply,'wizard-test'),1);
  assert.equal(countAction(expiredApply,'wizard-apply'),1,'Apply is never replayed by restart');
  await expiredApply.click('workflowApply');assert.equal(countAction(expiredApply,'wizard-apply'),2);

  const restartProbe=fixture();await workerStep(restartProbe);restartProbe.rejectAction='scheduler-status';await restartProbe.click('workflowStartWorker');
  assert.equal(restartProbe.nodes.get('workflowStartWorker').textContent,'Restart Worker','Probe admission race also has recovery control');
  assert.match(restartProbe.nodes.get('workflowWizardStatus').textContent,/This request was not queued/);
  assert(!/expired/.test(restartProbe.nodes.get('workflowWorkerStatus').textContent),'Permanent worker rejection does not claim a temporary expiry');
  restartProbe.rejectAction='';await restartProbe.click('workflowStartWorker');assert.equal(restartProbe.nodes.get('workflowNext').hidden,false);
  assert.deepEqual(restartProbe.modes,['setup','setup'],'Permanent recovery reuses the same setup scheduler path');
  assert(!restartProbe.requests.some(r=>r.fields&&/wizard-apply|restore|save-auto/.test(r.fields.action)));

  const permanentTakeover=fixture();temporaryWorker(permanentTakeover);await restoreStep(permanentTakeover);
  Object.assign(permanentTakeover.currentStatus,{setup_temporary:'no',setup_expires_epoch:'',worker_available:'no'});
  await permanentTakeover.context.SadlerWorkflow.refresh();
  assert.match(permanentTakeover.nodes.get('workflowWorkerStatus').textContent,/may have expired/,'Cleared lease markers alone preserve the temporary-expiry explanation');
  permanentTakeover.context.requestScheduler=async mode=>{permanentTakeover.modes.push(mode);permanentTakeover.currentStatus.worker_available='yes';return{ok:true,temporary:false,reused:true};};
  await permanentTakeover.click('workflowStartWorker');
  assert.equal(permanentTakeover.nodes.get('workflowRestoreRun').disabled,false);
  permanentTakeover.currentStatus.worker_available='no';await permanentTakeover.context.SadlerWorkflow.refresh();
  assert.match(permanentTakeover.nodes.get('workflowWorkerStatus').textContent,/Background processing is unavailable/);
  assert(!/one-hour|expired/.test(permanentTakeover.nodes.get('workflowWorkerStatus').textContent),'Verified permanent readiness clears obsolete temporary-expiry context');
  assert.equal(countAction(permanentTakeover,'restore'),0);

  const unrelatedAdmission=fixture();temporaryWorker(unrelatedAdmission);await restoreStep(unrelatedAdmission);
  unrelatedAdmission.rejectAction='restore';unrelatedAdmission.rejectionCode='settings_changed';await unrelatedAdmission.click('workflowRestoreRun');
  assert.equal(unrelatedAdmission.nodes.get('workflowWizardStatus').textContent,'Fixture request rejected','Unrelated response errors retain their actual message');
  assert.equal(unrelatedAdmission.nodes.get('workflowWorkerStatus').hidden,true);
  assert.equal(unrelatedAdmission.nodes.get('workflowStartWorker').textContent,'Recheck Worker');
  const unknownStatus=fixture();temporaryWorker(unknownStatus);await restoreStep(unknownStatus);
  unknownStatus.context.SadlerWorkflow.acceptStatus({queue_state:'inactive',setup_temporary:'yes',setup_expires_epoch:'1'});
  assert.equal(unknownStatus.nodes.get('workflowRestoreRun').disabled,false,'Cached queue and expired timestamps alone cannot revoke readiness');
  assert.equal(unknownStatus.nodes.get('workflowWorkerStatus').hidden,true);
  const originalStatusFetch=unknownStatus.context.fetch;
  unknownStatus.context.fetch=async(url,opts)=>{if(new URL(url).searchParams.get('api')==='status')throw new Error('Fixture offline');return originalStatusFetch(url,opts);};
  await assert.rejects(unknownStatus.context.SadlerWorkflow.refresh(),/Fixture offline/);
  assert.equal(unknownStatus.nodes.get('workflowWorkerStatus').hidden,true,'Network failures are not labelled as worker expiry');
  unknownStatus.context.fetch=originalStatusFetch;
  unknownStatus.transportFailure='restore';await unknownStatus.click('workflowRestoreRun');
  assert.match(unknownStatus.nodes.get('workflowWizardStatus').textContent,/uncertain/);
  assert.equal(unknownStatus.nodes.get('workflowRestoreRun').disabled,true);
  assert.equal(unknownStatus.nodes.get('workflowStartWorker').disabled,true,'Uncertain restore cannot restart/replay processing');
  await unknownStatus.click('workflowStartWorker');await unknownStatus.click('workflowRestoreRun');
  assert.equal(countAction(unknownStatus,'restore'),1);
  assert.equal(countAction(unknownStatus,'scheduler-status'),1);

  const uncertainFinish=fixture();await restoreStep(uncertainFinish);await uncertainFinish.click('workflowRestoreRun');await uncertainFinish.click('workflowContinueApplied');
  uncertainFinish.transportFailure='finish-setup';await uncertainFinish.click('workflowFinish');
  assert.match(uncertainFinish.nodes.get('workflowWizardStatus').textContent,/uncertain/);
  assert.equal(uncertainFinish.nodes.get('workflowFinish').disabled,true,'An uncertain Finish cannot be replayed');
  assert.equal(uncertainFinish.nodes.get('workflowStartWorker').disabled,true);
  await uncertainFinish.click('workflowFinish');assert.equal(countAction(uncertainFinish,'finish-setup'),1);
  assert.equal(countAction(uncertainFinish,'save-auto'),0,'Uncertain Finish does not change renewal preference');

  const stopped=fixture();temporaryWorker(stopped);await restoreStep(stopped);
  Object.assign(stopped.currentStatus,{package_running:'no',worker_available:'no'});await stopped.context.SadlerWorkflow.refresh();
  assert.match(stopped.nodes.get('workflowWorkerStatus').textContent,/Start the package in Package Center/);
  assert(!/expired/.test(stopped.nodes.get('workflowWorkerStatus').textContent));
  const beforeStoppedModes=stopped.modes.length;await stopped.click('workflowStartWorker');
  assert.equal(stopped.modes.length,beforeStoppedModes,'A stopped package cannot be started through automatic wizard recovery');
  Object.assign(stopped.currentStatus,{package_running:'yes',uninstall_ready:'yes'});await stopped.context.SadlerWorkflow.refresh();
  assert.match(stopped.nodes.get('workflowWorkerStatus').textContent,/prepared for uninstall/);
  assert.equal(stopped.nodes.get('workflowStartWorker').disabled,true);
  assert.equal(stopped.nodes.get('workflowExit').disabled,false);

  const preparedResume=fixture();await restoreStep(preparedResume);await preparedResume.click('workflowRestoreRun');await preparedResume.click('workflowContinueApplied');
  Object.assign(preparedResume.currentStatus,{worker_available:'no',uninstall_ready:'yes'});await preparedResume.context.SadlerWorkflow.refresh();
  assert.equal(preparedResume.nodes.get('workflowStartWorker').disabled,true);
  assert.equal(preparedResume.nodes.get('workflowBack').hidden,true);
  Object.assign(preparedResume.currentStatus,{package_running:'yes',worker_available:'yes',uninstall_ready:'no'});await preparedResume.context.SadlerWorkflow.refresh();
  assert.equal(preparedResume.nodes.get('workflowStartWorker').disabled,false,'Fresh resumed status releases the recovery control in committed Finish');
  assert.equal(preparedResume.nodes.get('workflowFinish').disabled,true,'Resumed availability alone cannot prove readiness');
  assert.equal(preparedResume.nodes.get('workflowWorkerReady').hidden,true);
  assert.equal(countAction(preparedResume,'restore'),1);
  await preparedResume.click('workflowStartWorker');
  assert.equal(preparedResume.nodes.get('workflowFinish').disabled,false,'A matching readiness receipt permits explicit Finish after resume');
  assert.equal(countAction(preparedResume,'restore'),1,'Resuming never replays the committed restore');

  const f=fixture();await f.open();
  assert.equal(f.nodes.get('wfEmail').value,initial.email);
  await f.click('workflowNext');f.nodes.get('wfDomains').value='new.example.com';f.nodes.get('wfToken').value=fixtureToken;
  f.nodes.get('wfKey').value='rsa-4096';f.nodes.get('wfDescription').value='New certificate';
  await f.click('workflowNext');
  assert.equal(f.config.domains[0],'example.com','Next must not commit draft');
  assert.equal(f.nodes.get('configuredDomains').textContent,initial.domains.join('\n'),'Draft edits must not change Dashboard saved settings');
  assert(!f.requests.some(r=>r.fields),'Moving through input steps must not POST settings');
  await f.click('workflowBack');assert.equal(f.nodes.get('wfDomains').value,'new.example.com','Back retains draft');
  await f.click('workflowNext');await f.click('workflowStartWorker');await f.click('workflowNext');
  assert.equal(f.nodes.get('workflowApply').disabled,true,'Apply must wait for staging success');
  await f.click('workflowStage');
  assert.equal(f.config.domains[0],'example.com','Staging must not commit');
  assert.equal(f.nodes.get('configuredDescription').textContent,initial.cert_desc,'Staging must not display draft settings as committed');
  assert.equal(f.nodes.get('workflowApply').disabled,false,'Exact durable job receipt permits apply');
  await f.click('workflowApply');assert.equal(f.config.domains[0],'new.example.com');
  assert.equal(f.nodes.get('wfToken').value,'','Cloudflare token input must clear after commit');
  assert.equal(f.nodes.get('certificateSettings').querySelector('[name="domains"]').value,'new.example.com','Main settings must reflect committed wizard data');
  assert.equal(f.nodes.get('configuredDomains').textContent,'new.example.com','Dashboard must refresh immediately after Apply without reopening');
  assert.equal(f.nodes.get('configuredDescription').textContent,'New certificate');
  assert.equal(f.nodes.get('configuredKey').textContent,'RSA 4096');
  assert.equal(f.nodes.get('configuredToken').textContent,'Token configured: Yes');
  await f.click('workflowContinueApplied');await f.click('workflowFinish');
  assert.deepEqual(f.modes,['setup','ensure','cleanup-setup']);
  assert(f.requests.some(r=>r.fields&&r.fields.action==='finish-setup'));
  assert.equal(f.config.auto_renew,'1','Existing renewal preference survives wizard');
  await f.click('workflowExit');assert.equal(f.nodes.get('workflowModal').classList.contains('open'),false);

  // A scheduler/API acknowledgement or another completed job is not enough:
  // Finish must await its own worker receipt, then a successful settings save.
  const finishing=fixture();await finishing.open();await finishing.click('workflowNext');await finishing.click('workflowNext');await finishing.click('workflowStartWorker');await finishing.click('workflowNext');await finishing.click('workflowStage');await finishing.click('workflowApply');await finishing.click('workflowContinueApplied');
  const waitFor=async predicate=>{for(let i=0;i<200;i++){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,2));}assert(predicate(),'Workflow did not reach the expected state');};
  const countFinishAction=action=>finishing.requests.filter(r=>r.fields&&r.fields.action===action).length;
  finishing.deferAction='finish-setup';await finishing.click('workflowFinish');
  assert.equal(finishing.nodes.get('workflowFinish').textContent,'Finishing setup…');
  assert.equal(finishing.nodes.get('workflowFinish').disabled,true);
  assert.equal(countFinishAction('save-auto'),0,'Renewal preference must wait for the exact completed Finish job');
  assert(!/Setup complete/.test(finishing.nodes.get('workflowWizardStatus').textContent));
  await finishing.click('workflowFinish');assert.equal(countFinishAction('finish-setup'),1,'Busy Finish cannot queue a duplicate');
  finishing.completePending('failed');await waitFor(()=>!finishing.nodes.get('workflowFinish').disabled);
  assert.match(finishing.nodes.get('workflowWizardStatus').textContent,/remained busy/);
  assert.equal(countFinishAction('save-auto'),0);
  assert.equal(finishing.nodes.get('workflowExit').textContent,'Exit Setup');
  await finishing.click('workflowFinish');finishing.failSaveAuto=true;finishing.completePending('completed');
  await waitFor(()=>!finishing.nodes.get('workflowFinish').disabled);
  assert.match(finishing.nodes.get('workflowWizardStatus').textContent,/settings changed/);
  assert.equal(finishing.nodes.get('workflowExit').textContent,'Exit Setup','Failed renewal save must not report setup complete');
  finishing.failSaveAuto=false;await finishing.click('workflowFinish');finishing.completePending('completed');
  await waitFor(()=>finishing.nodes.get('workflowExit').textContent==='Close');
  assert.match(finishing.nodes.get('workflowWizardStatus').textContent,/Setup complete.*enabled/);
  assert.equal(countFinishAction('wizard-apply'),1,'Finish retries do not repeat certificate application');

  const failed=fixture();failed.failAction='wizard-test';await failed.open();await failed.click('workflowNext');await failed.click('workflowNext');await failed.click('workflowStartWorker');await failed.click('workflowNext');await failed.click('workflowStage');
  assert.equal(failed.nodes.get('workflowApply').disabled,true);assert.match(failed.nodes.get('workflowWizardStatus').textContent,/failed/);
  assert.deepEqual(failed.config,initial);
  await failed.click('workflowExit');assert.equal(failed.nodes.get('workflowModal').classList.contains('open'),false);assert.deepEqual(failed.config,initial);

  const retest=fixture();await retest.open();await retest.click('workflowNext');await retest.click('workflowNext');await retest.click('workflowStartWorker');await retest.click('workflowNext');await retest.click('workflowStage');assert.equal(retest.nodes.get('workflowApply').disabled,false);
  retest.failAction='wizard-test';await retest.click('workflowStage');assert.equal(retest.nodes.get('workflowApply').disabled,true,'Failed re-test must revoke earlier staging success');

  const uncertain=fixture();await uncertain.open();await uncertain.click('workflowNext');uncertain.nodes.get('wfDomains').value='changed.example.com';await uncertain.click('workflowNext');await uncertain.click('workflowStartWorker');await uncertain.click('workflowNext');await uncertain.click('workflowStage');uncertain.transportFailure='wizard-apply';await uncertain.click('workflowApply');
  assert.equal(uncertain.config.domains[0],'changed.example.com','Fixture committed before response loss');
  assert.equal(uncertain.nodes.get('workflowApply').disabled,true,'An uncertain commit must not be replayed');assert.match(uncertain.nodes.get('workflowWizardStatus').textContent,/uncertain/);

  const temporary=fixture();temporary.context.requestScheduler=async mode=>{temporary.modes.push(mode);if(mode==='setup'){temporary.currentStatus.setup_temporary='yes';return{ok:true,temporary:true,created:true};}return{ok:true};};
  await temporary.open();await temporary.click('workflowNext');await temporary.click('workflowNext');await temporary.click('workflowStartWorker');
  assert.match(temporary.nodes.get('workflowWizardStatus').textContent,/Temporary setup processing was started/,'Fresh setup must describe temporary processing rather than reused permanent automation');
  await temporary.click('workflowExit');
  assert.deepEqual(temporary.modes,['setup','cleanup-setup']);assert(temporary.requests.some(r=>r.fields&&r.fields.action==='cancel-setup'));assert.deepEqual(temporary.config,initial);

  const switchMode=fixture();await switchMode.open(backup);switchMode.nodes.get('workflowNew').checked=true;await switchMode.nodes.get('workflowNew').dispatch('change');await switchMode.flush();
  assert.equal(switchMode.nodes.get('workflowAutoRenew').checked,true,'Restore→New reloads saved renewal choice');

  const restored=fixture({config:{...initial,email:'',domains:[],cert_desc:'SadlerACME wildcard',auto_renew:'0'},hasToken:false});await restored.open(backup);await restored.click('workflowNext');
  assert.equal(restored.nodes.get('configuredDomains').textContent,'','Selecting a backup must not change saved Dashboard domains');
  assert.equal(restored.nodes.get('configuredToken').textContent,'Token configured: No');
  assert.equal(restored.nodes.get('wfDomains').readOnly,true,'Restore domain/key edits are deferred until after verified restore');
  await restored.click('workflowNext');assert.match(restored.nodes.get('workflowWizardStatus').textContent,/token/);
  restored.nodes.get('wfToken').value=fixtureToken;await restored.click('workflowNext');await restored.click('workflowStartWorker');await restored.click('workflowNext');await restored.click('workflowRestoreRun');
  assert.equal(restored.config.auto_renew,'0');assert(!restored.requests.some(r=>r.fields&&r.fields.action==='wizard-apply'),'Restore must not issue or apply');
  assert.equal(restored.nodes.get('wfToken').value,'','Restore clears token input');
  assert.equal(restored.nodes.get('configuredDomains').textContent,initial.domains.join('\n'),'Restore must refresh Dashboard domains without reopening');
  assert.equal(restored.nodes.get('configuredDescription').textContent,initial.cert_desc);
  assert.equal(restored.nodes.get('configuredKey').textContent,'ECC P-384');
  assert.equal(restored.nodes.get('configuredToken').textContent,'Token configured: Yes','Restore must show saved token presence from the safe response');
  for (const id of ['configuredDescription','configuredDomains','configuredKey','configuredToken']) assert(!restored.nodes.get(id).textContent.includes(fixtureToken),'Dashboard must never expose the token value');
  await restored.click('workflowContinueApplied');assert.equal(restored.nodes.get('workflowAutoRenew').disabled,true,'Unusable recovered certificate cannot enable renewal');

  const restoreFailure=fixture();restoreFailure.failAction='restore';await restoreFailure.open(backup);await restoreFailure.click('workflowNext');restoreFailure.nodes.get('wfToken').value=fixtureToken;await restoreFailure.click('workflowNext');await restoreFailure.click('workflowStartWorker');await restoreFailure.click('workflowNext');await restoreFailure.click('workflowRestoreRun');
  assert.match(restoreFailure.nodes.get('workflowWizardStatus').textContent,/Fixture operation failed/);
  assert(restoreFailure.nodes.get('workflowWizardStatus').classList.contains('error'),'Restore failure remains an error');
  assert(!/preparation|uninstall/i.test(restoreFailure.nodes.get('workflowWizardStatus').textContent),'Restore errors must not suggest uninstall preparation');
  assert.deepEqual(restoreFailure.config,initial,'Failed restore must not be shown as committed');
  assert.equal(restoreFailure.nodes.get('configuredDomains').textContent,initial.domains.join('\n'),'Failed restore keeps the saved Dashboard values');

  const empty=fixture();await empty.open({...backup,settings:{...initial,email:'',domains:[]}});await empty.click('workflowNext');empty.nodes.get('wfToken').value=fixtureToken;await empty.click('workflowNext');
  assert.equal(empty.nodes.get('workflowHeading').textContent,'Start background processing','Untouched settings-only backup remains restorable');

  const backupFailure=fixture();backupFailure.failAction='backup';await backupFailure.click('workflowDownload');
  assert.match(backupFailure.nodes.get('workflowDownloadStatus').textContent,/Fixture operation failed/);
  assert(backupFailure.nodes.get('workflowDownloadStatus').classList.contains('error'),'Backup failure remains an error');
  assert.match(backupFailure.nodes.get('workflowDownloadStatus').textContent,/Check Logs.*Retry Download Backup/);
  assert(!/preparation|uninstall/i.test(backupFailure.nodes.get('workflowDownloadStatus').textContent),'Backup failure guidance must concern the backup action');
  assert(!backupFailure.requests.some(r=>r.fields&&r.fields.action==='download-backup'),'Failed export must not fetch or trigger a download');
  assert.equal(backupFailure.nodes.get('workflowDownload').disabled,false,'Backup button is available after failure');

  const removal=fixture();await removal.click('workflowPrepare');assert.match(removal.nodes.get('workflowPrepareStatus').textContent,/Choose whether/);assert.equal(removal.modes.length,0);
  removal.nodes.get('workflowBackupSkip').checked=true;await removal.nodes.get('workflowBackupSkip').dispatch('change');await removal.click('workflowPrepare');
  assert.deepEqual(removal.modes,['setup','remove-all']);assert(removal.requests.some(r=>r.fields&&r.fields.action==='prepare-uninstall'));assert(!removal.requests.some(r=>r.fields&&/delete-data|purge/.test(r.fields.action)),'Preparation never deletes app data');
  const preparedMessage=removal.nodes.get('workflowPrepareStatus').textContent, preparedRequests=removal.requests.length;
  await removal.click('workflowGoToBackup');
  assert.equal(removal.nodes.get('workflowBackupSkip').checked,true,'The backup link preserves the uninstall acknowledgement');
  assert.equal(removal.nodes.get('workflowPrepareStatus').textContent,preparedMessage,'Switching pages preserves preparation feedback');
  assert.equal(removal.requests.length,preparedRequests,'The backup link only navigates');
  assert.match(removal.nodes.get('workflowReadiness').textContent,/Ready to uninstall.*kept your data/);

  const removalFailure=fixture();removalFailure.failAction='prepare-uninstall';removalFailure.nodes.get('workflowBackupSkip').checked=true;await removalFailure.nodes.get('workflowBackupSkip').dispatch('change');await removalFailure.click('workflowPrepare');
  assert.match(removalFailure.nodes.get('workflowPrepareStatus').textContent,/Fixture operation failed/);
  assert(removalFailure.nodes.get('workflowPrepareStatus').classList.contains('error'));
  assert.match(removalFailure.nodes.get('workflowPrepareStatus').textContent,/If preparation cannot complete, open the Manual recovery instructions on this page/);
  assert.equal(removalFailure.currentStatus.uninstall_ready,'no','Failed preparation must not report readiness');

  const auth=fixture();const pending=auth.realScheduler('setup');await auth.flush();assert.equal(auth.bridge.length,1);assert.equal(auth.bridge[0].data.password,'');
  const id=auth.bridge[0].data.requestId;
  auth.sendBridge({type:'sadleracme.scheduler.result',requestId:id,ok:true},'https://attacker.invalid');
  auth.sendBridge({type:'sadleracme.scheduler.result',requestId:id,ok:false,needsPassword:true,message:'Confirm'});await auth.flush();
  auth.nodes.get('workflowPassword').value='fixture-dsm-password';await auth.nodes.get('workflowPasswordForm').dispatch('submit');await auth.flush();
  assert.equal(auth.nodes.get('workflowPassword').value,'','Password input clears immediately');
  assert(auth.requests.some(r=>r.fields&&r.fields.action==='automation-intent'),'Ambiguous task creation must block untouched-install bypass');
  assert(!auth.requests.some(r=>r.options.body&&r.options.body.includes('fixture-dsm-password')),'DSM password must never reach CGI');
  assert.equal(auth.bridge[1].data.password,'fixture-dsm-password');
  auth.sendBridge({type:'sadleracme.scheduler.result',requestId:auth.bridge[1].data.requestId,ok:true,created:true,temporary:true});assert.equal((await pending).created,true);
  assert.equal(auth.nodes.get('workflowPasswordModal').classList.contains('open'),false);
  console.log('PASS: workflow validation, draft isolation, durable job correlation, fresh startup diagnostics, stale-error isolation, cached-queue rejection, correlated readiness and timeout, bounded GET recovery without POST replay, uncertain commit guard, apply/restore boundaries, token clearing, staging retry, empty backup restore, temporary cleanup, uninstall preparation, action-specific backup/restore/preparation errors, single wizard file picker and launcher, invalid/cancelled/replaced files, stale-read and exited-wizard isolation, temporary-expiry and typed-admission recovery, preserved backup/token/hash/staging result, restart authentication cancellation, committed Restore/Finish recovery, permanent-worker reuse and verified takeover clearing temporary-expiry context, stopped/prepared guidance and resumed committed-Finish recovery, unrelated-error preservation, uncertain restore/Finish no-replay, cross-panel busy controls, state-preserving backup navigation, Logs navigation, settings synchronization, immediate Dashboard refresh after Apply and Restore, draft isolation in summaries, token-presence-only display, task order, password isolation and delayed/failed/successful Finish completion.');
}

module.exports = { fixture, initial, fixtureToken, backup };
if (require.main === module) runSuite().catch(error=>{console.error(error);process.exitCode=1;});
