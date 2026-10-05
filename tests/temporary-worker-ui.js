/* Focused temporary-worker DOM fixtures; no real DSM, DNS or certificate operations. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const {fixture, initial, fixtureToken} = require('./workflow-ui.js');
const source = process.env.SADLER_UI_SOURCE ? fs.readFileSync(process.env.SADLER_UI_SOURCE, 'utf8') : undefined;
const tests = [];
const test = (name, fn) => tests.push({name, fn});
const make = options => fixture({...options, source});
const count = (f, action) => f.requests.filter(r => r.fields && r.fields.action === action).length;
const isOpen = f => f.nodes.get('workflowModal').classList.contains('open');
const text = f => f.nodes.get('workflowWizardStatus').textContent;
const noCertificateAction = f => {
  for (const action of ['wizard-test', 'wizard-apply', 'restore', 'redeploy', 'finish-setup', 'save-auto']) {
    assert.equal(count(f, action), 0, 'Worker management must not submit ' + action);
  }
};
function scheduler(f, created = false) {
  f.context.requestScheduler = async mode => {
    f.modes.push(mode);
    if (mode === 'setup') {
      Object.assign(f.currentStatus, {worker_available:'yes', queue_state:'active', setup_temporary:'yes'});
      return {ok:true, temporary:true, created, reused:!created};
    }
    return {ok:true, tasksAbsent:true};
  };
}
async function step3(f) {
  await f.open(); await f.click('workflowNext');
  f.nodes.get('wfDescription').value = 'Draft kept across worker restart';
  f.nodes.get('wfDomains').value = 'lab.example.com';
  f.nodes.get('wfToken').value = fixtureToken;
  await f.click('workflowNext');
}
async function ready(created = false) {
  const f = make(); scheduler(f, created); await step3(f); await f.click('workflowStartWorker'); return f;
}
async function expire(f) {
  Object.assign(f.currentStatus, {worker_available:'no', queue_state:'inactive', setup_temporary:'no', setup_expires_epoch:''});
  await f.context.SadlerWorkflow.refresh(); await f.flush();
}
function draftKept(f) {
  assert.equal(f.nodes.get('wfDescription').value, 'Draft kept across worker restart');
  assert.equal(f.nodes.get('wfDomains').value, 'lab.example.com');
  assert.equal(f.nodes.get('wfToken').value, fixtureToken);
  assert.deepEqual(f.config, initial, 'Worker operations must not commit settings');
}

test('New temporary processing retains its started wording and exit cleanup', async () => {
  const f = await ready(true);
  assert.match(text(f), /Temporary setup processing was started/);
  await f.click('workflowExit');
  assert.deepEqual(f.modes, ['setup', 'cleanup-setup']);
  assert.equal(count(f, 'cancel-setup'), 1); assert(!isOpen(f)); noCertificateAction(f);
});

test('Reused temporary processing is not described as permanent', async () => {
  const f = await ready();
  assert.match(text(f), /Temporary setup processing was reused/);
  assert(!/permanent/.test(text(f))); draftKept(f);
});

test('Reused temporary processing removes its task before cancelling the lease on exit', async () => {
  const f = await ready(), order = [], fetch = f.context.fetch, requestScheduler = f.context.requestScheduler;
  f.context.requestScheduler = async mode => { order.push(mode); return requestScheduler(mode); };
  f.context.fetch = async (url, opts) => {
    if (opts && opts.body) order.push(JSON.parse(opts.body).action);
    return fetch(url, opts);
  };
  await f.click('workflowExit');
  assert.deepEqual(order, ['cleanup-setup', 'cancel-setup']);
  assert.equal(count(f, 'cancel-setup'), 1); assert(!isOpen(f));
  assert.equal(f.nodes.get('wfToken').value, ''); assert.deepEqual(f.config, initial); noCertificateAction(f);
});

test('Expired reused task is still removed on exit without restarting or cancelling an absent lease', async () => {
  const f = await ready(); await expire(f); await f.click('workflowExit');
  assert.deepEqual(f.modes, ['setup', 'cleanup-setup']);
  assert.equal(count(f, 'cancel-setup'), 0); assert(!isOpen(f)); noCertificateAction(f);
});

test('Reused task ownership survives a failed readiness receipt for explicit cleanup', async () => {
  const f = make(); scheduler(f); f.failAction = 'scheduler-status';
  await step3(f); await f.click('workflowStartWorker');
  assert.match(text(f), /Fixture operation failed/); assert(f.nodes.get('workflowNext').hidden);
  await f.click('workflowExit');
  assert.deepEqual(f.modes, ['setup', 'cleanup-setup']);
  assert.equal(count(f, 'cancel-setup'), 1); assert(!isOpen(f)); noCertificateAction(f);
});

async function failedBridgeStart(temporary) {
  const f = make(); await step3(f); f.context.requestScheduler = f.realScheduler;
  await f.click('workflowStartWorker');
  assert.equal(f.bridge.length, 1);
  f.sendBridge({type:'sadleracme.scheduler.result', requestId:f.bridge[0].data.requestId,
    ok:false, taskSaved:true, temporary, message:'Task exists but could not be started'});
  await f.flush(); assert.match(text(f), /could not be started/);
  f.context.requestScheduler = async mode => { f.modes.push(mode); return {ok:true, tasksAbsent:true}; };
  f.currentStatus.setup_temporary = 'no';
  await f.click('workflowExit'); return f;
}

test('Failed saved temporary task remains an explicit cleanup responsibility', async () => {
  const f = await failedBridgeStart(true);
  assert.deepEqual(f.modes, ['cleanup-setup']); assert(!isOpen(f)); noCertificateAction(f);
});

test('Failed permanent startup is not mistaken for a temporary cleanup responsibility', async () => {
  const f = await failedBridgeStart(false);
  assert.deepEqual(f.modes, []); assert.equal(count(f, 'cancel-setup'), 0); assert(!isOpen(f)); noCertificateAction(f);
});

test('Established permanent automation is reused and untouched by wizard exit', async () => {
  const f = make(); await step3(f); await f.click('workflowStartWorker');
  assert.match(text(f), /Existing permanent automation was reused/);
  await f.click('workflowExit');
  assert.deepEqual(f.modes, ['setup']); assert.equal(count(f, 'cancel-setup'), 0); noCertificateAction(f);
});

test('Merely viewing a wizard does not claim a temporary task it never started or reused', async () => {
  const f = make(); f.currentStatus.setup_temporary = 'yes'; await step3(f); await f.click('workflowExit');
  assert.deepEqual(f.modes, []); assert.equal(count(f, 'cancel-setup'), 0); assert(!isOpen(f));
});

test('Permanent takeover prevents lease cancellation during later temporary-task cleanup', async () => {
  const f = await ready();
  Object.assign(f.currentStatus, {setup_temporary:'no', worker_available:'yes', queue_state:'active'});
  await f.click('workflowExit');
  assert.deepEqual(f.modes, ['setup', 'cleanup-setup']);
  assert.equal(count(f, 'cancel-setup'), 0); assert.equal(f.currentStatus.worker_available, 'yes');
});

test('Cancelling DSM deletion approval keeps the wizard and cleanup obligation for explicit retry', async () => {
  const f = await ready(); f.context.requestScheduler = f.realScheduler;
  await f.click('workflowExit'); assert.equal(f.bridge.length, 1);
  assert.equal(f.bridge[0].data.mode, 'cleanup-setup');
  const response = {type:'sadleracme.scheduler.result', requestId:f.bridge[0].data.requestId, ok:false, needsPassword:true, message:'Confirm task deletion'};
  f.sendBridge(response, 'https://untrusted.invalid'); await f.flush();
  assert(!f.nodes.get('workflowPasswordModal').classList.contains('open'), 'Foreign-origin replies cannot request approval');
  f.sendBridge(response, f.context.location.origin, {}); await f.flush();
  assert(!f.nodes.get('workflowPasswordModal').classList.contains('open'), 'Wrong-window replies cannot request approval');
  f.sendBridge(response); await f.flush();
  assert(f.nodes.get('workflowPasswordModal').classList.contains('open'));
  await f.click('workflowPasswordCancel'); assert(isOpen(f)); draftKept(f);
  assert.match(text(f), /cancelled.*Temporary setup was not confirmed removed/);
  assert.equal(count(f, 'cancel-setup'), 0);
  scheduler(f); await f.click('workflowExit');
  assert(!isOpen(f)); assert.equal(count(f, 'cancel-setup'), 1);
  assert.equal(f.nodes.get('workflowPassword').value, ''); noCertificateAction(f);
});

test('Rejected task deletion does not close the wizard or claim cleanup succeeded', async () => {
  const f = await ready();
  f.context.requestScheduler = async mode => { f.modes.push(mode); throw new Error('DSM refused task deletion'); };
  await f.click('workflowExit'); assert(isOpen(f)); draftKept(f);
  assert.match(text(f), /DSM refused task deletion.*Temporary setup was not confirmed removed/);
  assert.equal(count(f, 'cancel-setup'), 0);
  scheduler(f); await f.click('workflowExit');
  assert(!isOpen(f)); assert.equal(count(f, 'cancel-setup'), 1); noCertificateAction(f);
});

test('Failed lease cleanup leaves the wizard open and can be explicitly retried', async () => {
  const f = await ready(); f.failAction = 'cancel-setup'; await f.click('workflowExit');
  assert(isOpen(f)); draftKept(f); assert.match(text(f), /Temporary setup was not confirmed removed/);
  f.failAction = ''; await f.click('workflowExit');
  assert(!isOpen(f)); assert.equal(count(f, 'cancel-setup'), 2); noCertificateAction(f);
});

for (const created of [true, false]) test((created ? 'New' : 'Reused') + ' worker expiry clears only stale readiness and offers Restart Worker', async () => {
  const f = await ready(created); assert.match(text(f), /Worker is ready/);
  await expire(f);
  assert.equal(text(f), ''); assert(!f.nodes.get('workflowWizardStatus').classList.contains('success'));
  assert.match(f.nodes.get('workflowWorkerStatus').textContent, /Temporary processing is unavailable/);
  assert.equal(f.nodes.get('workflowStartWorker').textContent, 'Restart Worker');
  assert(f.nodes.get('workflowWorkerReady').hidden); assert(f.nodes.get('workflowNext').hidden); draftKept(f);
  const probes = count(f, 'scheduler-status'); scheduler(f); await f.click('workflowStartWorker');
  assert.equal(count(f, 'scheduler-status'), probes + 1, 'Restart requires its own readiness receipt');
  assert(f.nodes.get('workflowWorkerStatus').hidden);
  assert.match(text(f), /Temporary setup processing was reused/); draftKept(f); noCertificateAction(f);
  await f.click('workflowNext'); assert(f.nodes.get('workflowApply').disabled);
  assert.match(f.nodes.get('workflowReview').textContent, /lab.example.com/);
});

test('Expiry does not erase a prior staging outcome or replay staging after restart', async () => {
  const f = await ready(); await f.click('workflowNext'); await f.click('workflowStage');
  const before = text(f); assert.match(before, /Staging test succeeded/);
  await expire(f); assert.equal(text(f), before); assert(f.nodes.get('workflowApply').disabled);
  await f.click('workflowStartWorker');
  assert.equal(count(f, 'wizard-test'), 1); assert.equal(count(f, 'wizard-apply'), 0);
  assert.equal(f.nodes.get('workflowApply').disabled, false, 'An unchanged tested draft remains eligible for explicit Apply; no action is replayed');
});

test('Expiry does not erase a certificate failure message', async () => {
  const f = await ready(); await f.click('workflowNext'); f.failAction = 'wizard-test'; await f.click('workflowStage');
  const before = text(f); assert.match(before, /Fixture operation failed/);
  await expire(f); assert.equal(text(f), before); assert(f.nodes.get('workflowWizardStatus').classList.contains('error'));
});

test('Expiry does not erase a successful settings-commit result', async () => {
  const f = await ready(); await f.click('workflowNext'); await f.click('workflowStage'); await f.click('workflowApply');
  const before = text(f); assert.match(before, /Certificate applied and settings saved/);
  await expire(f); assert.equal(text(f), before); assert.equal(count(f, 'wizard-apply'), 1);
});

test('Fresh startup rejection keeps its error instead of retaining the old green readiness banner', async () => {
  const f = await ready(); await expire(f);
  f.context.requestScheduler = async () => { throw new Error('DSM confirmation cancelled'); };
  await f.click('workflowStartWorker');
  assert.match(text(f), /DSM confirmation cancelled/); assert(!/Worker is ready/.test(text(f)));
  assert(f.nodes.get('workflowWizardStatus').classList.contains('error')); draftKept(f); noCertificateAction(f);
});

test('An unconfirmed or cached expiry alone does not manufacture worker unavailability', async () => {
  const f = await ready();
  f.context.SadlerWorkflow.acceptStatus({queue_state:'inactive', setup_temporary:'yes', setup_expires_epoch:'1'});
  assert.equal(f.nodes.get('workflowWorkerStatus').hidden, true);
  assert.match(text(f), /Worker is ready/, 'This change responds to confirmed worker availability, not a browser clock guess');
});

(async () => {
  let failed = 0;
  console.log('Workflow source: ' + (process.env.SADLER_UI_SOURCE || 'src/ui/workflow.js'));
  for (const {name, fn} of tests) {
    try { await fn(); console.log('PASS: ' + name); }
    catch (error) { failed++; console.error('FAIL: ' + name + '\n' + error.stack); }
  }
  console.log(`${tests.length - failed}/${tests.length} tests passed`);
  if (failed) process.exitCode = 1;
})().catch(error => {console.error(error); process.exitCode = 1;});
