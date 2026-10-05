/* SadlerACME optional setup and recovery UI. Drafts and secrets stay in memory. */
(function (global) {
  'use strict';
  var MAX_BACKUP = 524288;
  var settingsKeys = ['email', 'domains', 'key_type', 'cert_desc', 'default_on_create', 'auto_renew', 'dns_sleep'];

  function cleanConfig(source) {
    source = source || {};
    var result = {};
    settingsKeys.forEach(function (key) {
      if (key === 'domains') result[key] = Array.isArray(source[key]) ? source[key].slice() : [];
      else if (key === 'auto_renew' || key === 'default_on_create') result[key] = String(source[key]) === '1' ? '1' : '0';
      else result[key] = typeof source[key] === 'string' || typeof source[key] === 'number' ? String(source[key]) : '';
    });
    result.key_type = result.key_type || 'ec-384';
    result.cert_desc = result.cert_desc || 'SadlerACME wildcard';
    result.dns_sleep = result.dns_sleep || '60';
    result.cf_token = '';
    return result;
  }
  function domainsFromText(value) {
    return String(value).split(/[\r\n,]+/).map(function (s) { return s.trim().toLowerCase(); }).filter(function (s, n, all) { return s && all.indexOf(s) === n; });
  }
  function validateConfig(config, hasToken) {
    if (!/^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(config.email)) throw new Error('Enter a valid ACME account email using letters, digits and standard email punctuation.');
    if (!Array.isArray(config.domains) || !config.domains.length || config.domains.length > 100 || config.domains.some(function (d) { return d.length > 253 || !/^(\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(d); })) throw new Error('Enter between 1 and 100 valid DNS names, one per line.');
    if (['ec-384', 'ec-256', 'rsa-4096', 'rsa-2048'].indexOf(config.key_type) < 0) throw new Error('Choose a supported key type.');
    if (!config.cert_desc || config.cert_desc.length > 80) throw new Error('Certificate description must contain 1–80 characters.');
    if (!/^\d+$/.test(config.dns_sleep) || Number(config.dns_sleep) < 30 || Number(config.dns_sleep) > 600) throw new Error('DNS propagation wait must be 30–600 seconds.');
    if (config.cf_token && !/^[A-Za-z0-9_-]{20,256}$/.test(config.cf_token)) throw new Error('The Cloudflare token format is invalid.');
    if (!config.cf_token && !hasToken) throw new Error('Enter your Cloudflare API token. Recovery backups do not contain it.');
    return config;
  }
  function previewBackup(text) {
    if (new TextEncoder().encode(text).length > MAX_BACKUP) throw new Error('The recovery file is too large (maximum 512 KiB).');
    var data;
    try { data = JSON.parse(text); } catch (_) { throw new Error('Choose a valid SadlerACME JSON recovery backup.'); }
    if (!data || data.format !== 'SadlerACME' || data.version !== 1 || !data.settings || typeof data.settings !== 'object' || Array.isArray(data.settings)) throw new Error('This is not a supported SadlerACME recovery backup.');
    if ('cf_token' in data.settings) throw new Error('The recovery file unexpectedly contains a Cloudflare token. Use a backup created by the current version.');
    return data;
  }
  function jobOutcome(status, id) {
    if (status.last_job !== id) return null;
    if (status.last_job_result === 'completed') return true;
    if (status.last_job_result === 'failed' || status.last_job_result === 'interrupted') return false;
    return null;
  }
  var helpers = { cleanConfig: cleanConfig, domainsFromText: domainsFromText, validateConfig: validateConfig, previewBackup: previewBackup, jobOutcome: jobOutcome };
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
  if (!global.document) return;

  var document = global.document;
  var options = global.SadlerWorkflowConfig || {};
  var state = null;
  var importReadSequence = 0;
  var wizardOpening = false;
  var importPlaceholder = 'Choose a recovery file to preview its date, domains and certificate.';
  var backupAcknowledged = false;
  var panelBusy = false;
  var lastStatus = null;
  var returnFocus = null;
  var schedulerPending = null;
  var recoveryUrl = options.recoveryUrl || 'RECOVERY.md';
  function el(id) { return document.getElementById(id); }
  function delay(ms) { return new Promise(function (resolve) { global.setTimeout(resolve, ms); }); }
  function endpoint(api, params) {
    var url = new URL(global.location.href);
    url.hash = '';
    url.searchParams.delete('api');
    if (api) url.searchParams.set('api', api);
    Object.keys(params || {}).forEach(function (key) { url.searchParams.set(key, params[key]); });
    return url.toString();
  }
  function csrf() {
    var input = document.querySelector('input[name="csrf"]');
    return options.csrf || (input && input.value) || '';
  }
  function readResponse(response) {
    return response.json().catch(function () { throw new Error('DSM did not return a valid response. Reopen SadlerACME from the DSM desktop if your session has expired.'); }).then(function (data) {
      if (!response.ok || data.ok === false) throw Object.assign(new Error(data.message || 'Request failed (HTTP ' + response.status + ').'), { responseRejected: true, code: typeof data.code === 'string' ? data.code : '' });
      return data;
    });
  }
  function get(api, params) { return global.fetch(endpoint(api, params), { cache: 'no-store', credentials: 'same-origin' }).then(readResponse); }
  function post(action, fields, signal) {
    return global.fetch(endpoint(), { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({}, fields || {}, { action: action, csrf: csrf() })) }).then(readResponse);
  }
  function acceptStatus(data) {
      lastStatus = data;
      var previousWorkerBlock = state && state.workerBlocked;
      if (state) {
        if (data.uninstall_ready === 'yes') state.workerBlocked = 'prepared';
        else if (data.package_running === 'no') state.workerBlocked = 'stopped';
        else if (data.package_running === 'yes' && data.uninstall_ready === 'no') state.workerBlocked = '';
      }
      if (state && data.setup_temporary === 'yes') {
        state.workerWasTemporary = true;
        state.workerExpiresEpoch = data.setup_expires_epoch || state.workerExpiresEpoch;
      }
      if (state && (data.worker_available === 'no' && state.worker || state.workerBlocked)) {
        state.worker = false;
        state.workerUnavailable = true;
        render();
      } else if (state && state.workerBlocked !== previousWorkerBlock) render();
      var ready = el('workflowReadiness');
      if (ready) ready.textContent = data.uninstall_ready === 'yes' ? 'Ready to uninstall in Package Center. Preparation has kept your data in place.' : 'Complete preparation before removing SadlerACME in Package Center.';
      var summary = el('workflowLastOperation');
      if (summary) summary.textContent = (data.message || 'No operation recorded.') + (data.last_run ? ' · ' + data.last_run : '');
      var activity = el('workflowActivity');
      if (activity) activity.hidden = data.setup_required === 'yes' && data.state === 'idle' &&
        (!data.last_action || data.last_action === 'None') && !data.active_job;
      var log = el('workflowLogText');
      if (log && el('workflowLogPanel') && !el('workflowLogPanel').hidden && typeof data.log === 'string') {
        var follow = log.scrollHeight - log.scrollTop - log.clientHeight < 55;
        log.textContent = data.log;
        if (follow) log.scrollTop = log.scrollHeight;
      }
      return data;
  }
  function status() { return get('status').then(acceptStatus); }
  function message(target, text, kind, category) {
    var node = el(target);
    if (!node) return;
    node.textContent = text || '';
    node.className = 'workflow-status' + (kind ? ' ' + kind : '');
    node.setAttribute('data-workflow-message', category || '');
  }
  function logs() {
    var button = document.querySelector('.tabbtn[data-tab="logs"]');
    if (button) {
      button.click();
      if (typeof global.scrollTo === 'function') global.scrollTo(0, 0);
    }
  }
  function watchJob(id, target) {
    if (!id) return Promise.reject(new Error('The server did not identify the queued operation. Check Logs before retrying.'));
    var deadline = Date.now() + 30 * 60 * 1000;
    var failures = 0;
    function poll() {
      return Promise.all([status(), get('job', { id: id })]).then(function (values) {
        var data = values[0], receipt = values[1];
        failures = 0;
        var result = receipt.job_id === id ? receipt.result === 'completed' ? true : receipt.result === 'failed' || receipt.result === 'interrupted' ? false : null : jobOutcome(data, id);
        if (result === true) return status().catch(function () { return acceptStatus({ status_unavailable: true, message: 'The operation completed, but status could not be refreshed. Check the connection before continuing.' }); }).then(function (fresh) { fresh.workflow_job_id = id; return fresh; });
        if (result === false) throw Object.assign(new Error(receipt.message || data.message || 'The operation failed. Open Logs for details.'), { operationFailed: true, outcomeKnown: true });
        if (Date.now() > deadline) throw Object.assign(new Error('The operation has not reported completion. It may still be running; check Logs before retrying.'), { operationFailed: true });
        if (data.active_job === id && data.message) message(target, data.message);
        return delay(1500).then(poll);
      }).catch(function (error) {
        if (error.operationFailed || ++failures > 4) { error.operationFailed = true; throw error; }
        return delay(2000).then(poll);
      });
    }
    return poll();
  }
  function job(action, fields, target) {
    target = target || 'workflowWizardStatus';
    var owner = state;
    return post(action, fields).catch(function (error) {
      if (error.responseRejected) error.outcomeKnown = true;
      if (owner && error.responseRejected && error.code === 'worker_unavailable') {
        owner.worker = false; owner.workerUnavailable = true;
        error.message = workerUnavailableText(owner) + ' This request was not queued. Your setup progress has been kept.';
      }
      throw error;
    }).then(function (response) {
      message(target, response.message || 'Operation queued…');
      return watchJob(response.job_id, target);
    }).catch(function (error) {
      if (owner && !error.outcomeKnown && ['wizard-apply', 'restore', 'wizard-test', 'redeploy', 'finish-setup'].indexOf(action) >= 0) {
        owner.uncertain = true;
        throw new Error(error.message + ' The result is uncertain, so repeating this operation is blocked. Check Logs, close and reopen SadlerACME, then review saved settings and certificate status before continuing.');
      }
      throw error;
    });
  }
  function scheduler(mode) {
    if (typeof global.requestScheduler !== 'function') return Promise.reject(new Error('DSM task management is unavailable. Reopen SadlerACME from the DSM desktop, or follow the manual recovery instructions.'));
    return global.requestScheduler(mode);
  }
  function requestScheduler(mode) {
    if (schedulerPending) return Promise.reject(new Error('A DSM confirmation is already in progress.'));
    if (global.parent === global) return Promise.reject(new Error('Open SadlerACME from the DSM desktop to authorize task changes, or use the manual instructions.'));
    return new Promise(function (resolve, reject) {
      schedulerPending = { mode: mode, resolve: resolve, reject: reject, timer: null, id: '', sending: false };
      sendScheduler('');
    });
  }
  function finishScheduler(error, result) {
    var pending = schedulerPending;
    if (!pending) return;
    global.clearTimeout(pending.timer);
    schedulerPending = null;
    el('workflowPassword').value = '';
    el('workflowPasswordModal').classList.remove('open');
    el('workflowPasswordModal').setAttribute('aria-hidden', 'true');
    if (error) pending.reject(error); else pending.resolve(result);
  }
  function sendScheduler(password) {
    var pending = schedulerPending;
    if (!pending || pending.sending) return;
    pending.sending = true;
    el('workflowPasswordSubmit').disabled = true;
    el('workflowPasswordCancel').disabled = true;
    el('workflowPassword').value = '';
    var intentTimer, intentController;
    var intent = Promise.resolve();
    if (password && (pending.mode === 'setup' || pending.mode === 'ensure')) {
      if (typeof global.AbortController === 'function') intentController = new global.AbortController();
      intent = Promise.race([post('automation-intent', null, intentController && intentController.signal), new Promise(function (_, reject) {
        intentTimer = global.setTimeout(function () { if (intentController) intentController.abort(); password = ''; reject(new Error('The app could not record task setup intent. No DSM task change was requested. Retry or use manual recovery.')); }, 15000);
      })]);
    }
    intent.then(function () {
      global.clearTimeout(intentTimer);
      if (schedulerPending !== pending) return;
      pending.id = 'sadler-workflow-' + Date.now() + '-' + Math.random().toString(36).slice(2);
      global.parent.postMessage({ type: 'sadleracme.scheduler.install', requestId: pending.id, mode: pending.mode, password: password }, global.location.origin);
      password = '';
      pending.timer = global.setTimeout(function () { finishScheduler(new Error('DSM did not confirm the task operation. Check Automation or manual recovery before retrying; a task may have been created.')); }, 60000);
    }).catch(function (error) { global.clearTimeout(intentTimer); password = ''; finishScheduler(error); });
  }
  function workerError(data) {
    return data && data.state === 'error' && ['setup', 'bootstrap', 'migration', 'preflight', 'recovery', 'worker'].indexOf(data.last_action) >= 0;
  }
  function workerErrorStamp(data) {
    return JSON.stringify([data.state, data.last_action, data.last_run, data.message]);
  }
  function waitWorker(target, before) {
    var deadline = Date.now() + 90000;
    var beforeStamp = workerErrorStamp(before), probe = '', readFailures = 0;
    function poll() {
      return Promise.all([status(), probe ? get('job', { id: probe }) : Promise.resolve(null)]).then(function (values) {
        readFailures = 0;
        var data = values[0], receipt = values[1];
        if (receipt && receipt.job_id === probe) {
          if (receipt.result === 'completed' && data.queue_state === 'active' && data.worker_available !== 'no') return data;
          if (receipt.result === 'failed' || receipt.result === 'interrupted') throw new Error(receipt.message || 'The worker readiness check failed. Open Logs for details.');
        }
        // Public status can outlive a failed attempt. Only a changed startup
        // error can stop this attempt; unrelated active jobs have their own receipts.
        if (workerError(data) && workerErrorStamp(data) !== beforeStamp && (!data.active_job || data.active_job === probe)) throw new Error('Background processing could not start: ' + data.message);
        if (Date.now() > deadline) throw new Error('The worker did not confirm readiness. Check Automation and the manual recovery instructions before continuing.' + (workerError(data) ? ' Last recorded worker error (which may be from an earlier attempt): ' + data.message : ''));
        message(target, 'Waiting for the SadlerACME worker to start…');
        // A cached active queue is not proof of a working process. Require a
        // durable receipt for this attempt's read-only scheduler status check.
        if (!probe && data.queue_state === 'active' && data.worker_available !== 'no') return post('scheduler-status', {}).then(function (response) {
          if (!response.job_id) throw new Error('The server did not identify the worker readiness check. Check Logs before retrying.');
          probe = response.job_id;
          return poll();
        });
        return delay(1500).then(poll);
      }, function (error) {
        // Retry only these GETs. A rejected probe POST or a real worker/receipt
        // failure must propagate without replaying any request or hiding it.
        if (++readFailures >= 4 || Date.now() >= deadline) throw error;
        return delay(Math.min(2000, deadline - Date.now())).then(poll);
      });
    }
    return poll();
  }
  function establishWorker(target, onCreated) {
    var schedulerResult, before;
    message(target, 'Checking existing automation. DSM may ask for password confirmation to start temporary setup.');
    return status().then(function (data) {
      before = data;
      if (state && state.workerBlocked) throw new Error(workerUnavailableText(state));
      return scheduler('setup');
    }).then(function (result) {
      schedulerResult = result;
      // A successfully started, recognised temporary task belongs to this
      // wizard's exit cleanup even when it existed before the wizard opened.
      // Record this before waiting for readiness so a failed probe can still
      // be followed by an explicit, DSM-authorised cleanup attempt.
      if (state && result && result.temporary === true) {
        state.workerWasTemporary = true;
        state.temporary = true;
      }
      if (result && result.temporary && result.created && onCreated) onCreated();
      return waitWorker(target, before);
    }).then(function (data) {
      data.workflow_temporary = !!(schedulerResult && schedulerResult.temporary === true);
      data.workflow_started_temporary = data.workflow_temporary && schedulerResult.created === true;
      if (state) {
        state.temporary = state.temporary || data.workflow_temporary;
        // A cleared lease alone can mean expiry. Clear its remembered hint only
        // after this attempt has a matching completed worker-readiness receipt.
        if (data.setup_temporary === 'no') { state.workerWasTemporary = false; state.workerExpiresEpoch = ''; }
      }
      return data;
    });
  }
  function button(text, fn, className) {
    var node = document.createElement('button');
    node.type = 'button'; node.className = 'btn ' + (className || ''); node.textContent = text;
    node.addEventListener('click', fn);
    return node;
  }
  function workerUnavailableText(owner) {
    if (owner.workerBlocked === 'stopped') return 'SadlerACME is stopped. Start the package in Package Center, then click Recheck Worker. Your setup progress has been kept.';
    if (owner.workerBlocked === 'prepared') return 'SadlerACME has been prepared for uninstall. Exit Setup and review Automation before resuming setup.';
    return (owner.workerWasTemporary ? 'Temporary processing is unavailable. Its one-hour setup session may have expired.' : 'Background processing is unavailable.') + ' Click Restart Worker, then retry the operation when it is ready.';
  }
  function render() {
    if (!state) return;
    var dialog = document.querySelector('.workflow-dialog');
    if (dialog) dialog.classList.toggle('with-log', !el('workflowLogPanel').hidden);
    // Invalidate only an old worker-readiness message. Keep certificate,
    // restore, staging and failure outcomes visible when processing stops.
    if (state.workerUnavailable && el('workflowWizardStatus').getAttribute('data-workflow-message') === 'worker-ready') {
      message('workflowWizardStatus', '');
    }
    var titles = ['Choose setup', 'Certificate settings', 'Start background processing', state.kind === 'restore' ? 'Restore and verify' : 'Test and apply', 'Finish setup'];
    el('workflowStep').textContent = 'Step ' + (state.step + 1) + ' of 5';
    el('workflowHeading').textContent = titles[state.step];
    document.querySelectorAll('[data-workflow-step]').forEach(function (node) { node.hidden = Number(node.getAttribute('data-workflow-step')) !== state.step; });
    el('workflowBack').hidden = state.step === 0 || state.committed;
    el('workflowNext').hidden = state.step > 2 || state.step === 2 && !state.worker;
    el('workflowExit').textContent = state.finished ? 'Close' : 'Exit Setup';
    el('workflowNewActions').hidden = state.kind === 'restore';
    el('workflowRestoreActions').hidden = state.kind !== 'restore';
    el('workflowStageWait').hidden = !(state.busy && state.operation === 'staging');
    el('workflowApply').disabled = state.busy || state.uncertain || !state.worker || !state.tested || state.committed;
    el('workflowStage').disabled = state.busy || state.uncertain || !state.worker || state.committed;
    el('workflowRestoreRun').disabled = state.busy || state.uncertain || !state.worker || state.committed;
    el('workflowContinueApplied').hidden = !state.committed;
    el('workflowWorkerControls').hidden = state.finished || state.step < 2 && !state.workerAttempted;
    el('workflowStartWorker').hidden = false;
    el('workflowWorkerReady').hidden = !state.worker || !!state.closing;
    el('workflowStartWorker').textContent = state.workerBlocked === 'stopped' ? 'Recheck Worker' : state.workerUnavailable ? 'Restart Worker' : state.worker ? 'Recheck Worker' : 'Check / Start Worker';
    el('workflowWorkerStatus').textContent = state.workerUnavailable ? workerUnavailableText(state) : '';
    el('workflowWorkerStatus').hidden = !state.workerUnavailable || !!state.closing;
    el('workflowFinish').disabled = state.busy || state.uncertain || state.workerUnavailable || state.finished;
    el('workflowRestoredRedeploy').disabled = state.busy || state.uncertain || !state.worker;
    el('workflowFinish').textContent = state.busy && state.step === 4 ? 'Finishing setup…' : 'Finish Setup';
    el('workflowAutoRenew').disabled = state.busy || state.finished;
    if (state.kind === 'restore' && state.committed && (!lastStatus || lastStatus.restore_requires_issue === 'yes' || lastStatus.local_cert_available !== 'yes' || lastStatus.dsm_match !== 'yes')) {
      el('workflowAutoRenew').disabled = true;
      el('workflowAutoRenew').checked = false;
    }
    el('workflowRenewalRequirement').hidden = !(state.kind === 'restore' && state.committed && el('workflowAutoRenew').disabled && !state.busy && !state.finished);
    el('workflowRestoredRedeploy').hidden = !(state.kind === 'restore' && state.committed && lastStatus && lastStatus.local_cert_available === 'yes' && lastStatus.dsm_match !== 'yes');
    var restore = state.kind === 'restore';
    el('workflowTokenHelp').textContent = restore ? 'Enter the Cloudflare token again. It is not included in recovery backups.' : state.hasToken ? 'A token is already saved. Leave blank to keep it, or enter a replacement.' : 'Required. The token is used for Cloudflare DNS-01 validation.';
    el('workflowRestoreSettingsNote').hidden = !restore;
    document.querySelectorAll('#workflowFields [name]').forEach(function (field) {
      if (field.name === 'cf_token') { field.readOnly = state.busy || state.committed; return; }
      if (field.tagName === 'SELECT' || field.type === 'checkbox') field.disabled = restore || state.committed || state.busy;
      else field.readOnly = restore || state.committed || state.busy;
    });
    ['workflowNew', 'workflowRestore', 'workflowRestoreFile'].forEach(function (id) { el(id).disabled = state.busy || state.committed; });
    el('workflowReview').textContent = state.draft.domains.join('\n') + '\nDescription: ' + state.draft.cert_desc + '\nKey: ' + state.draft.key_type + (lastStatus && lastStatus.dsm_id ? '\nExisting DSM certificate ID: ' + lastStatus.dsm_id : '\nDSM destination will be checked before applying.');
    el('workflowFooterNote').textContent = state.committed ? 'Settings have been committed. Finish configures startup and renewal.' : 'Next and Back keep a temporary draft. Saved settings are unchanged until Apply & Save or Restore Backup.';
    document.querySelectorAll('#workflowModal button').forEach(function (node) {
      if (node.id === 'workflowViewLogs') { node.disabled = false; return; }
      if (state.busy || state.uncertain && node.id !== 'workflowExit') node.disabled = true;
      else if (['workflowApply', 'workflowStage', 'workflowRestoreRun', 'workflowRestoredRedeploy', 'workflowFinish'].indexOf(node.id) < 0) node.disabled = false;
    });
    if (state.readingBackup) el('workflowNext').disabled = true;
    if (state.workerBlocked === 'prepared') el('workflowStartWorker').disabled = true;
  }
  function fillFields() {
    document.querySelectorAll('#workflowFields [name]').forEach(function (field) {
      var value = state.draft[field.name];
      if (field.type === 'checkbox') field.checked = value === '1';
      else field.value = Array.isArray(value) ? value.join('\n') : value || '';
    });
  }
  function captureFields() {
    document.querySelectorAll('#workflowFields [name]').forEach(function (field) {
      if (field.name === 'domains') state.draft.domains = domainsFromText(field.value);
      else if (field.type === 'checkbox') state.draft[field.name] = field.checked ? '1' : '0';
      else state.draft[field.name] = field.value.trim();
    });
  }
  function run(fn) {
    if (!state || state.busy) return;
    state.busy = true; render();
    return Promise.resolve().then(fn).catch(function (error) {
      if (state && error.responseRejected && error.code === 'worker_unavailable') {
        state.worker = false; state.workerUnavailable = true;
        message('workflowWizardStatus', workerUnavailableText(state) + ' This request was not queued. Your setup progress has been kept.', 'error');
      } else message('workflowWizardStatus', error.message, 'error');
    }).finally(function () { if (state) { state.busy = false; state.closing = false; state.operation = ''; render(); } });
  }
  function refreshSaved() {
    return get('settings').then(function (data) {
      if (state) { state.hash = data.settings_hash; state.hasToken = !!data.has_token; }
      return data;
    });
  }
  function syncSavedForm(data) {
    // These summaries describe committed settings, never the wizard draft.
    var keyType = data.config.key_type || 'ec-384';
    var keyLabels = { 'ec-384': 'ECC P-384', 'ec-256': 'ECC P-256', 'rsa-4096': 'RSA 4096', 'rsa-2048': 'RSA 2048' };
    var summaries = {
      configuredDescription: data.config.cert_desc || 'SadlerACME wildcard',
      configuredDomains: Array.isArray(data.config.domains) ? data.config.domains.join('\n') : '',
      configuredKey: keyLabels[keyType] || keyType,
      configuredToken: 'Token configured: ' + (data.has_token ? 'Yes' : 'No')
    };
    Object.keys(summaries).forEach(function (id) {
      var summary = el(id);
      if (summary) summary.textContent = summaries[id];
    });
    var form = el('certificateSettings');
    if (!form) return;
    var fields = Array.from(form.querySelectorAll('[name]')).concat(Array.from(document.querySelectorAll('[form="certificateSettings"]')));
    fields.forEach(function (field) {
      if (field.name === 'cf_token') {
        field.value = '';
        var tokenState = field.parentNode && field.parentNode.querySelector('.muted');
        if (tokenState) tokenState.textContent = 'Token saved: ' + (data.has_token ? 'Yes' : 'No');
        return;
      }
      if (settingsKeys.indexOf(field.name) < 0) return;
      var value = data.config[field.name];
      if (field.type === 'checkbox') field.checked = String(value) === '1';
      else field.value = Array.isArray(value) ? value.join('\n') : String(value == null ? '' : value);
    });
    if (el('auto')) el('auto').checked = String(data.config.auto_renew) === '1';
  }
  function openWizard(backup, restoreMode) {
    if (state || panelBusy || wizardOpening) return;
    returnFocus = document.activeElement;
    wizardOpening = true; panelControls();
    var restoring = !!backup || restoreMode === true;
    if (restoring) message('workflowRestoreStatus', '');
    return Promise.all([get('settings'), status()]).then(function (values) {
      var saved = values[0];
      state = { step: 0, kind: restoring ? 'restore' : 'new', backup: backup || null, draft: cleanConfig(backup ? backup.settings : saved.config), hash: saved.settings_hash, hasToken: !!saved.has_token, worker: false, workerAttempted: false, workerUnavailable: false, workerWasTemporary: values[1].setup_temporary === 'yes', temporary: false, tested: false, committed: false, busy: false, finished: false, uncertain: false, readingBackup: false };
      state.workerBlocked = values[1].uninstall_ready === 'yes' ? 'prepared' : values[1].package_running === 'no' ? 'stopped' : '';
      state.workerUnavailable = !!state.workerBlocked;
      state.workerExpiresEpoch = values[1].setup_expires_epoch || '';
      if (restoring) { state.hasToken = false; state.draft.auto_renew = '0'; }
      el('workflowNew').checked = !restoring;
      el('workflowRestore').checked = restoring;
      el('workflowRestoreFileWrap').hidden = !restoring;
      el('workflowRestoreFile').value = '';
      el('workflowBackupPreview').textContent = backup ? backupPreviewText(backup) : importPlaceholder;
      el('workflowAutoRenew').checked = !restoring && state.draft.auto_renew === '1';
      message('workflowWizardStatus', '');
      el('workflowLogPanel').hidden = true; el('workflowLogText').textContent = ''; el('workflowViewLogs').textContent = 'View Logs';
      fillFields(); render();
      el('workflowModal').classList.add('open'); el('workflowModal').setAttribute('aria-hidden', 'false');
      el('workflowHeading').focus();
    }).catch(function (error) { message(restoring ? 'workflowRestoreStatus' : 'workflowWizardStatus', error.message, 'error'); global.alert(error.message); }).finally(function () { wizardOpening = false; panelControls(); });
  }
  function closeWizard() {
    if (!state || state.busy) return;
    if (!state.finished && !global.confirm(state.uncertain ? 'The last operation may still be running or may have completed. Exit this wizard, then check Logs and saved settings before starting another operation. Saved changes will not be undone.' : state.committed ? 'Close setup? Settings already applied or restored will remain saved. You can reopen the wizard to finish automation.' : 'Exit setup and discard this wizard’s draft? Settings already saved outside the wizard are not changed.')) return;
    state.closing = true;
    var finish = function () {
      el('workflowModal').classList.remove('open'); el('workflowModal').setAttribute('aria-hidden', 'true');
      document.querySelectorAll('#workflowFields [name]').forEach(function (field) { if (field.type !== 'checkbox') field.value = ''; });
      resetRestoreSelection(true);
      state.draft.cf_token = ''; state.backup = null; state = null;
      panelControls();
      if (returnFocus && returnFocus.focus) returnFocus.focus();
    };
    run(function () {
      return status().then(function (data) {
        if (!state.temporary) { finish(); return; }
        message('workflowWizardStatus', 'Removing temporary setup resources. DSM may request a fresh password confirmation.');
        return scheduler('cleanup-setup').then(function () { return data.setup_temporary === 'yes' ? job('cancel-setup') : null; }).then(finish);
      }).catch(function (error) {
        throw new Error(error.message + ' Temporary setup was not confirmed removed. Retry Exit Setup, or open Uninstall for manual recovery. The temporary worker has a bounded lease.');
      });
    });
  }
  function backupPreviewText(backup) {
    return 'Created: ' + (backup.created_at || 'Unknown') + '\nDomains: ' + (Array.isArray(backup.settings.domains) ? backup.settings.domains.join(', ') : 'None') + '\nCertificate: ' + (backup.certificate ? 'Included' : 'Not included') + '\nCloudflare token and DSM password: not included';
  }
  function readBackupFile(file) {
    if (!file) return Promise.reject(new Error('Choose a SadlerACME recovery backup.'));
    if (file.size > MAX_BACKUP) return Promise.reject(new Error('The recovery file is too large (maximum 512 KiB).'));
    return file.text().then(previewBackup);
  }
  function panelControls() {
    var blocked = panelBusy || wizardOpening || !!state;
    document.querySelectorAll('#tab-backup button, #tab-uninstall button, #tab-uninstall input[name="workflowBackupChoice"]').forEach(function (node) {
      node.disabled = node.classList.contains('workflow-action-logs') || node.classList.contains('workflow-action-nav') ? false : blocked;
    });
  }
  function resetRestoreSelection(clearInput) {
    importReadSequence++;
    if (state) { state.backup = null; state.readingBackup = false; }
    if (clearInput) el('workflowRestoreFile').value = '';
    el('workflowBackupPreview').textContent = importPlaceholder;
    message('workflowWizardStatus', '');
  }
  function selectRestoreFile() {
    if (!state || state.busy || state.committed) return;
    resetRestoreSelection(false);
    state.draft = cleanConfig({}); state.hasToken = false; state.tested = false;
    el('workflowAutoRenew').checked = false; fillFields();
    var file = el('workflowRestoreFile').files[0], owner = state;
    if (!file) { render(); return; }
    var selection = importReadSequence;
    state.readingBackup = true; render();
    el('workflowBackupPreview').textContent = 'Reading recovery file…';
    return readBackupFile(file).then(function (backup) {
      if (state !== owner || selection !== importReadSequence) return;
      state.backup = backup; state.kind = 'restore';
      state.draft = cleanConfig(backup.settings); state.draft.auto_renew = '0';
      el('workflowBackupPreview').textContent = backupPreviewText(backup);
      fillFields();
    }).catch(function (error) {
      if (state !== owner || selection !== importReadSequence) return;
      resetRestoreSelection(true);
      message('workflowWizardStatus', error.message, 'error');
    }).finally(function () {
      if (state !== owner) return;
      if (selection === importReadSequence) state.readingBackup = false;
      render();
    });
  }
  function panelRun(target, fn, failureGuidance) {
    if (panelBusy || wizardOpening || state) return;
    panelBusy = true;
    panelControls();
    return Promise.resolve().then(fn).catch(function (error) { message(target, error.message + (failureGuidance ? '\n' + failureGuidance : ''), 'error'); }).finally(function () { panelBusy = false; panelControls(); });
  }
  function downloadBackup() {
    var createdTemporary = false;
    return panelRun('workflowDownloadStatus', function () {
      var operationError = null;
      return establishWorker('workflowDownloadStatus', function () { createdTemporary = true; }).then(function () { return job('backup', {}, 'workflowDownloadStatus'); }).then(function (data) {
        var transfer = data.workflow_job_id && data.workflow_job_id.replace(/\.job$/, '');
        if (!transfer) throw new Error('Backup completed but no download was published. Retry Download Backup.');
        return global.fetch(endpoint(), { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'download-backup', transfer_id: transfer, csrf: csrf() }) }).then(function (response) {
          if (!response.ok) return readResponse(response);
          return response.blob();
        });
      }).then(function (blob) {
        if (!(blob instanceof Blob)) throw new Error('The server did not return a downloadable backup.');
        if (blob.size > MAX_BACKUP) throw new Error('The server returned an oversized recovery backup.');
        return blob.text().then(function (text) { previewBackup(text); return blob; });
      }).then(function (blob) {
        var href = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = href; link.download = 'SadlerACME-recovery-' + new Date().toISOString().slice(0, 10) + '.json';
        document.body.appendChild(link); link.click(); link.remove();
        global.setTimeout(function () { URL.revokeObjectURL(href); }, 60000);
        message('workflowDownloadStatus', 'Download started. Confirm the file is saved before preparing for uninstall. It contains private keys; store it securely. Cloudflare tokens and DSM passwords are excluded.', 'success');
      }).catch(function (error) { operationError = error; }).then(function () {
        if (createdTemporary) return scheduler('cleanup-setup').then(function () { return status(); }).then(function (data) { return data.setup_temporary === 'yes' ? job('cancel-setup', {}, 'workflowDownloadStatus') : null; }).catch(function (error) { operationError = new Error((operationError ? operationError.message + ' ' : 'The download was started. ') + 'Temporary setup cleanup was not confirmed: ' + error.message); });
      }).then(function () {
        if (operationError) throw operationError;
        message('workflowDownloadStatus', 'Download started' + (createdTemporary ? ' and temporary setup was stopped' : '') + '. Confirm the file is saved. It contains private keys; store it securely. Cloudflare tokens and DSM passwords are excluded.', 'success');
      });
    }, 'Check Logs for details. Retry Download Backup once the reported problem is resolved.');
  }
  function prepareUninstall() {
    if (!backupAcknowledged) { message('workflowPrepareStatus', 'Choose whether you have saved a recovery backup or will continue without one. You can download a backup from Backup & Restore.', 'error'); return; }
    if (!global.confirm('Prepare SadlerACME for uninstall? Background processing will stop and SadlerACME tasks will be removed. Preparation does not delete your data. Completing uninstall in Package Center deletes SadlerACME data; DSM-installed certificates remain.')) return;
    panelRun('workflowPrepareStatus', function () {
      return establishWorker('workflowPrepareStatus').then(function () { message('workflowPrepareStatus', 'Removing SadlerACME bootstrap and temporary tasks. DSM may request password confirmation.'); return scheduler('remove-all'); }).then(function () { return job('prepare-uninstall', {}, 'workflowPrepareStatus'); }).then(function (data) {
        if (data.uninstall_ready !== 'yes') throw new Error('Preparation did not report ready. Do not assume background processing has been removed.');
        message('workflowPrepareStatus', 'Ready to uninstall. Open Package Center and uninstall SadlerACME. Preparation has preserved your data; completing uninstall will delete it. DSM-installed certificates and assignments will remain.', 'success');
      });
    }, 'If preparation cannot complete, open the Manual recovery instructions on this page.');
  }
  function bind() {
    global.requestScheduler = requestScheduler;
    global.addEventListener('message', function (event) {
      var pending = schedulerPending, result = event.data || {};
      if (!pending || event.origin !== global.location.origin || event.source !== global.parent || result.type !== 'sadleracme.scheduler.result' || result.requestId !== pending.id) return;
      global.clearTimeout(pending.timer); pending.timer = null; pending.sending = false;
      if (result.needsPassword) {
        el('workflowPasswordMessage').textContent = result.message || 'DSM requires administrator confirmation for this task change.';
        el('workflowPasswordSubmit').disabled = false; el('workflowPasswordCancel').disabled = false;
        el('workflowPasswordModal').classList.add('open'); el('workflowPasswordModal').setAttribute('aria-hidden', 'false');
        el('workflowPassword').focus(); return;
      }
      if (!result.ok) {
        if (state && pending.mode === 'setup' && result.taskSaved && result.temporary === true) state.temporary = true;
        finishScheduler(new Error((result.message || 'DSM task operation failed.') + (result.taskSaved ? ' A task may remain installed; use Exit Setup, Backup & Removal or manual recovery if needed.' : ''))); return;
      }
      finishScheduler(null, result);
    });
    el('workflowPasswordForm').addEventListener('submit', function (event) { event.preventDefault(); var password = el('workflowPassword').value; el('workflowPassword').value = ''; if (password) sendScheduler(password); password = ''; });
    el('workflowPasswordCancel').addEventListener('click', function () { finishScheduler(new Error('DSM confirmation cancelled. Your setup progress has been kept.')); });
    el('workflowPasswordModal').addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && schedulerPending && !schedulerPending.sending) { event.preventDefault(); finishScheduler(new Error('DSM confirmation cancelled. Your setup progress has been kept.')); }
      if (event.key === 'Tab') {
        var nodes = Array.from(el('workflowPasswordModal').querySelectorAll('input,button')).filter(function (node) { return !node.disabled; });
        if (!nodes.length) { event.preventDefault(); return; }
        if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes[nodes.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === nodes[nodes.length - 1]) { event.preventDefault(); nodes[0].focus(); }
      }
    });
    el('workflowExit').addEventListener('click', closeWizard);
    el('workflowBack').addEventListener('click', function () { captureFields(); state.step--; message('workflowWizardStatus', ''); render(); });
    el('workflowNext').addEventListener('click', function () {
      try {
        if (state.step === 0 && state.kind === 'restore' && !state.backup) throw new Error('Choose a recovery backup before continuing.');
        if (state.step === 1) {
          captureFields();
          if (state.kind === 'restore') { if (!/^[A-Za-z0-9_-]{20,256}$/.test(state.draft.cf_token)) throw new Error('Enter your Cloudflare API token. Recovery backups do not contain it.'); }
          else validateConfig(state.draft, state.hasToken);
          state.tested = false;
        }
        state.step++; message('workflowWizardStatus', ''); render();
      } catch (error) { message('workflowWizardStatus', error.message, 'error'); }
    });
    el('workflowNew').addEventListener('change', function () {
      if (!this.checked) return;
      resetRestoreSelection(true);
      run(function () { return refreshSaved().then(function (saved) { state.kind = 'new'; state.backup = null; state.draft = cleanConfig(saved.config); el('workflowAutoRenew').checked = state.draft.auto_renew === '1'; fillFields(); el('workflowRestoreFileWrap').hidden = true; }); });
    });
    el('workflowRestore').addEventListener('change', function () { if (this.checked) { resetRestoreSelection(true); state.kind = 'restore'; state.hasToken = false; state.draft = cleanConfig({}); el('workflowAutoRenew').checked = false; el('workflowRestoreFileWrap').hidden = false; fillFields(); render(); } });
    el('workflowRestoreFile').addEventListener('change', selectRestoreFile);
    el('workflowRestoreFile').addEventListener('cancel', function () {
      if (!state || state.busy || state.committed) return;
      resetRestoreSelection(true); state.draft = cleanConfig({}); state.hasToken = false; state.tested = false;
      fillFields(); render();
    });
    el('workflowStartWorker').addEventListener('click', function () {
      state.workerAttempted = true; state.worker = false;
      run(function () { return establishWorker('workflowWizardStatus').then(function (data) {
        state.worker = true; state.workerUnavailable = false;
        var readyText = data && data.workflow_temporary
          ? (data.workflow_started_temporary
            ? 'Worker is ready. Temporary setup processing was started for this wizard.'
            : 'Worker is ready. Temporary setup processing was reused for this wizard.')
          : 'Worker is ready. Existing permanent automation was reused.';
        message('workflowWizardStatus', readyText + (state.step >= 3 ? ' Your setup progress has been kept. Choose the operation again when ready.' : ''), 'success', 'worker-ready');
      }); });
    });
    el('workflowStage').addEventListener('click', function () {
      state.tested = false; state.operation = 'staging';
      run(function () {
        return job('wizard-test', { config: state.draft, expected_settings_hash: state.hash }).then(function () { state.tested = true; message('workflowWizardStatus', 'Staging test succeeded. Saved production settings and the DSM certificate are unchanged. Choose Apply & Save when ready.', 'success'); });
      });
    });
    el('workflowApply').addEventListener('click', function () {
      if (!global.confirm('Apply this certificate configuration and save it? SadlerACME may request a production certificate and update the matched DSM certificate entry. The destination is checked before issuance. Settings are committed only after successful application.')) return;
      run(function () {
        return job('wizard-apply', { config: state.draft, expected_settings_hash: state.hash }).then(function () { state.committed = true; state.draft.cf_token = ''; el('wfToken').value = ''; return refreshSaved(); }).then(function (saved) { syncSavedForm(saved); message('workflowWizardStatus', 'Certificate applied and settings saved. Continue to finish startup and automatic renewal.', 'success'); });
      });
    });
    el('workflowRestoreRun').addEventListener('click', function () {
      if (!global.confirm('Restore this backup and replace SadlerACME’s saved settings and recovery state? Automatic renewal will be disabled. DSM-installed certificates are not changed, and no certificate is requested.')) return;
      run(function () {
        return job('restore', { backup: state.backup, config: state.draft, expected_settings_hash: state.hash }).then(function (data) { state.committed = true; state.draft.cf_token = ''; el('wfToken').value = ''; state.backup = null; el('workflowAutoRenew').checked = false; message('workflowWizardStatus', 'Backup restored. Automatic renewal is disabled. ' + (data.restore_requires_issue === 'yes' ? 'The recovered state requires Issue / Apply from Certificate settings before renewal can be enabled. No new certificate has been requested.' : 'Check the certificate result; use Re-deploy Existing only if DSM needs the recovered certificate.'), 'success'); return refreshSaved(); }).then(syncSavedForm);
      });
    });
    el('workflowRestoredRedeploy').addEventListener('click', function () {
      if (!global.confirm('Deploy the restored certificate to DSM? This uses the recovered certificate and does not request a new certificate.')) return;
      run(function () { return job('redeploy').then(function () { message('workflowWizardStatus', 'Recovered certificate deployed to DSM.', 'success'); }); });
    });
    el('workflowContinueApplied').addEventListener('click', function () { state.step = 4; message('workflowWizardStatus', ''); render(); });
    el('workflowFinish').addEventListener('click', function () {
      run(function () {
        message('workflowWizardStatus', 'Checking the permanent bootstrap task. DSM may request fresh password confirmation.');
        return scheduler('ensure').then(function () { return scheduler('cleanup-setup'); }).then(function () { return job('finish-setup'); }).then(function () {
          // The completed Finish receipt confirms permanent automation takeover.
          state.workerWasTemporary = false; state.workerExpiresEpoch = '';
          return refreshSaved();
        }).then(function () {
          message('workflowWizardStatus', 'Automation verified. Saving the automatic renewal setting…');
          return post('save-auto', { auto_renew: el('workflowAutoRenew').checked ? '1' : '0', expected_settings_hash: state.hash });
        }).then(refreshSaved).then(function (saved) {
          syncSavedForm(saved);
          state.finished = true; state.temporary = false;
          message('workflowWizardStatus', 'Setup complete. Automatic renewal is ' + (el('workflowAutoRenew').checked ? 'enabled.' : 'disabled; enable it later in Automation.'), 'success');
        });
      });
    });
    el('workflowViewLogs').addEventListener('click', function () {
      var panel = el('workflowLogPanel'); panel.hidden = !panel.hidden;
      this.textContent = panel.hidden ? 'View Logs' : 'Hide Logs';
      document.querySelector('.workflow-dialog').classList.toggle('with-log', !panel.hidden);
      if (!panel.hidden) { el('workflowLogText').textContent = lastStatus && lastStatus.log || 'Loading log…'; status().catch(function () { el('workflowLogText').textContent = 'Log refresh failed. Check your DSM session and connection.'; }); }
    });
    el('workflowModal').addEventListener('keydown', function (event) {
      if (schedulerPending) return;
      if (event.key === 'Escape') { event.preventDefault(); closeWizard(); }
      if (event.key === 'Tab') {
        var nodes = Array.from(el('workflowModal').querySelectorAll('button,input,select,textarea,a[href]')).filter(function (node) { return !node.disabled && node.offsetParent !== null; });
        if (!nodes.length) return;
        if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes[nodes.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === nodes[nodes.length - 1]) { event.preventDefault(); nodes[0].focus(); }
      }
    });
    global.addEventListener('beforeunload', function (event) {
      if (state && (!state.finished || state.busy)) { event.preventDefault(); event.returnValue = ''; }
    });
    el('workflowDownload').addEventListener('click', downloadBackup);
    el('workflowRestoreButton').addEventListener('click', function () { return openWizard(null, true); });
    document.querySelectorAll('#tab-backup .workflow-action-logs, #tab-uninstall .workflow-action-logs').forEach(function (node) { node.addEventListener('click', logs); });
    el('workflowGoToBackup').addEventListener('click', function () {
      var target = document.querySelector('.tabbtn[data-tab="backup"]');
      if (target) { target.click(); if (typeof global.scrollTo === 'function') global.scrollTo(0, 0); }
    });
    document.querySelectorAll('[name="workflowBackupChoice"]').forEach(function (node) { node.addEventListener('change', function () { backupAcknowledged = true; }); });
    el('workflowPrepare').addEventListener('click', prepareUninstall);
  }
  function mount() {
    var settings = el('tab-settings');
    if (!settings) return;
    // One optional wizard; both heading entry points use the same controller.
    ['dashboard', 'settings'].forEach(function (page) {
      var pane = el('tab-' + page);
      var slot = pane && pane.querySelector('.wizard-heading-actions');
      if (!slot) return;
      var start = button('Setup Wizard', function () { openWizard(); });
      start.id = 'setupWizard-' + page;
      slot.appendChild(start);
    });
    var activity = document.createElement('div'); activity.id = 'workflowActivity'; activity.className = 'workflow-last-action'; activity.hidden = true;
    var summary = document.createElement('span'); summary.id = 'workflowLastOperation'; summary.className = 'muted'; summary.textContent = 'Current and last operation appear here.';
    activity.appendChild(summary); activity.appendChild(button('View Logs', logs, 'secondary')); (el('certificateOperations') || settings).appendChild(activity);
    var backup = el('tab-backup'), uninstall = el('tab-uninstall');
    if (!backup || !uninstall) return;
    backup.innerHTML = '<div class="page-heading"><h2>Backup &amp; Restore</h2><p class="muted">Keep a recovery copy or restore one through guided setup.</p></div><div class="workflow-recovery-grid">' +
      '<section id="workflowDownloadCard" class="card"><h2>Download a backup</h2><p>Save certificate keys, ACME recovery data and certificate settings to your computer.</p><dl class="workflow-facts"><div><dt>Certificate &amp; keys</dt><dd>Included when available</dd></div><div><dt>Cloudflare token</dt><dd>Not included</dd></div><div><dt>DSM password</dt><dd>Not included</dd></div></dl><div class="workflow-section-actions"><div class="workflow-buttons"><button id="workflowDownload" class="btn" type="button">Download Backup</button><button id="workflowDownloadLogs" class="btn secondary workflow-action-logs" type="button">View Logs</button></div><p class="workflow-small">Keep this file private: it contains private keys. Store it securely, preferably outside the NAS.</p><div id="workflowDownloadStatus" class="workflow-status" role="status" aria-live="polite"></div></div></section>' +
      '<section id="workflowRestoreCard" class="card"><h2>Restore a backup</h2><p>Open the setup wizard to select and preview your downloaded backup.</p><p>You will re-enter your Cloudflare token. DSM asks for administrator approval when needed.</p><p class="workflow-small">Saved settings and certificate data stay unchanged until you confirm Restore Backup. Restoring does not issue a certificate or change DSM-installed certificates.</p><div class="workflow-section-actions"><div class="workflow-buttons"><button id="workflowRestoreButton" class="btn secondary" type="button">Start Restore Wizard</button><button id="workflowRestoreLogs" class="btn secondary workflow-action-logs" type="button">View Logs</button></div><p class="workflow-small">Choose the file once, inside the wizard.</p><div id="workflowRestoreStatus" class="workflow-status" role="status" aria-live="polite"></div></div></section></div>';
    uninstall.innerHTML = '<div class="page-heading"><h2>Uninstall</h2><p class="muted">Prepare SadlerACME, then remove it through Package Center.</p></div><div class="workflow-recovery-grid">' +
      '<section id="workflowPrepareCard" class="card"><h2>Prepare for uninstall</h2><p>Closing this window does not stop SadlerACME’s background helpers or remove its Task Scheduler tasks.</p><p>Preparation stops the helpers and renewal, handles pending work, and removes SadlerACME’s scheduled tasks before Package Center uninstall.</p><p>Want to keep your certificate and recovery data for reinstalling? <button id="workflowGoToBackup" class="workflow-link workflow-action-nav" type="button">Download a backup first.</button></p><p class="workflow-small">Without a backup, setting up again may require a new certificate and use Let’s Encrypt issuance limits.</p><div class="workflow-choice"><input type="radio" name="workflowBackupChoice" id="workflowBackupSaved" value="saved"><label for="workflowBackupSaved">I have saved a recovery backup.</label></div><div class="workflow-choice"><input type="radio" name="workflowBackupChoice" id="workflowBackupSkip" value="skip"><label for="workflowBackupSkip">Continue without a backup. I understand recovery may require a new certificate.</label></div><div class="workflow-section-actions"><p id="workflowReadiness" class="workflow-readiness muted">Complete preparation before removing SadlerACME in Package Center.</p><div class="workflow-buttons"><button id="workflowPrepare" class="btn warn" type="button">Prepare for Uninstall</button><button id="workflowPrepareLogs" class="btn secondary workflow-action-logs" type="button">View Logs</button></div><p class="workflow-small">Preparation keeps your data in place.</p><div id="workflowPrepareStatus" class="workflow-status" role="status" aria-live="polite"></div></div></section>' +
      '<section id="workflowRecoveryCard" class="card"><h2>Manual recovery</h2><p>Use the SSH recovery instructions if preparation fails or SadlerACME cannot open.</p><p>Start with a read-only check. A last-resort removal option is available if the normal uninstaller is blocked.</p><div class="workflow-section-actions"><a id="workflowRecoveryLink" class="btn secondary workflow-link" target="_blank" rel="noopener">View SSH instructions</a><p class="workflow-small">Administrator access is required.</p></div></section></div><p class="workflow-removal-note"><strong>Package Center removal deletes SadlerACME’s data and stored keys.</strong> Certificates already installed in DSM remain in place, but SadlerACME will no longer renew them.</p>';
    el('workflowRecoveryLink').href = recoveryUrl;
    var modal = document.createElement('div'); modal.id = 'workflowModal'; modal.className = 'modalback'; modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = '<div class="modalbox workflow-dialog" role="dialog" aria-modal="true" aria-labelledby="workflowHeading"><div id="workflowStep" class="workflow-steps"></div><h2 id="workflowHeading" tabindex="-1">Setup Wizard</h2><div class="workflow-body">' +
      '<section data-workflow-step="0"><p>Choose a new configuration or restore a SadlerACME recovery backup. Existing saved settings load automatically.</p><div class="workflow-choice"><input id="workflowNew" type="radio" name="workflowKind" checked><label for="workflowNew">Set up or update the current configuration</label></div><div class="workflow-choice"><input id="workflowRestore" type="radio" name="workflowKind"><label for="workflowRestore">Restore a downloaded SadlerACME backup</label></div><div id="workflowRestoreFileWrap" hidden><label for="workflowRestoreFile">Recovery backup</label><input id="workflowRestoreFile" class="workflow-backup-file" type="file" accept=".json,application/json" aria-describedby="workflowBackupPreview"><div class="workflow-restore-preview"><h3>Backup preview</h3><div id="workflowBackupPreview" class="workflow-preview-text" role="status" aria-live="polite"></div><p class="workflow-preview-note">File summary only. Certificates are validated during restore.</p></div></div></section>' +
      '<section data-workflow-step="1" hidden><p>These values remain a draft until you apply or restore. Next does not save settings.</p><p id="workflowRestoreSettingsNote" class="workflow-small" hidden>Backup settings are shown for review. Restore them first; they can be edited through Settings afterwards.</p><div id="workflowFields" class="settingsgrid certificate-grid"><div class="cert-description"><label for="wfDescription">DSM certificate description</label><input id="wfDescription" name="cert_desc" maxlength="80"></div><div class="cert-key"><label for="wfKey">Key type</label><select id="wfKey" name="key_type"><option value="ec-384">ECC P-384</option><option value="ec-256">ECC P-256</option><option value="rsa-4096">RSA 4096</option><option value="rsa-2048">RSA 2048</option></select></div><div class="cert-domains"><label for="wfDomains">Domains / SANs — one per line</label><textarea id="wfDomains" name="domains"></textarea></div><div class="cert-options"><div><label for="wfDns">DNS propagation wait (seconds)</label><input id="wfDns" name="dns_sleep" type="number" min="30" max="600"></div><div class="check"><input id="wfDefault" name="default_on_create" type="checkbox"><label for="wfDefault">Set as default only when creating a new DSM certificate</label></div></div><div class="cert-email"><label for="wfEmail">ACME account email</label><input id="wfEmail" name="email" type="email" autocomplete="off"></div><div class="cert-token"><label for="wfToken">Cloudflare API token</label><input id="wfToken" name="cf_token" type="password" autocomplete="new-password"><div id="workflowTokenHelp" class="workflow-small"></div></div></div></section>' +
      '<section data-workflow-step="2" hidden><p>Existing working automation will be reused. A fresh setup starts a temporary worker for staging, restoration and certificate application. The permanent boot-up task is configured at the final step.</p><p class="workflow-small">DSM may ask for your administrator password. It goes directly to DSM and is not saved. Temporary processing lasts up to one hour. If it stops, use Restart Worker here to keep your setup progress. Closing this wizard uses a separate confirmation if DSM needs one to remove temporary tasks.</p></section>' +
      '<section data-workflow-step="3" hidden><div id="workflowReview" class="workflow-review"></div><div id="workflowNewActions"><p>Run the staging test against your draft first. It does not save production settings or change the certificate in DSM. Apply &amp; Save then uses or issues the production certificate and saves settings after successful application.</p><div class="workflow-buttons"><button id="workflowStage" class="btn secondary" type="button">Run Staging Test</button><button id="workflowApply" class="btn" type="button" disabled>Apply &amp; Save</button></div></div><p id="workflowStageWait" class="workflow-small workflow-stage-wait" role="status" hidden>Staging is running. DNS propagation and certificate checks can take a few minutes. Keep this window open; View Logs shows progress.</p><div id="workflowRestoreActions" hidden><p>Restore replaces SadlerACME settings and recovery data, with automatic renewal disabled. It does not change DSM-installed certificates or request a new certificate. Cryptographic and backup validation take place before importing.</p><button id="workflowRestoreRun" class="btn" type="button">Restore Backup</button><button id="workflowRestoredRedeploy" class="btn secondary" type="button" hidden>Re-deploy Existing</button></div><button id="workflowContinueApplied" class="btn" type="button" hidden>Continue to Finish</button></section>' +
      '<section data-workflow-step="4" hidden><p>Your certificate configuration has been saved. Finish verifies or installs the permanent bootstrap task and removes any temporary setup task.</p><div class="workflow-choice"><input id="workflowAutoRenew" type="checkbox"><label for="workflowAutoRenew">Enable automatic renewal checks every six hours</label></div><p id="workflowRenewalRequirement" class="workflow-required" hidden>Renewal will remain disabled. Review the recovered certificate in Certificate settings, then Issue / Apply or re-deploy it as appropriate before enabling renewal.</p><p class="workflow-small">DSM may request fresh password confirmation. If that is cancelled, your saved settings remain; finish later from this wizard or Automation.</p><button id="workflowFinish" class="btn" type="button">Finish Setup</button></section>' +
      '<div id="workflowWorkerControls" hidden><p id="workflowWorkerStatus" class="workflow-status error" role="status" aria-live="polite" hidden></p><button id="workflowStartWorker" class="btn secondary" type="button">Check / Start Worker</button><p id="workflowWorkerReady" class="good" hidden>Worker ready.</p></div><div id="workflowWizardStatus" class="workflow-status" role="status" aria-live="polite"></div></div><div id="workflowLogPanel" hidden><pre id="workflowLogText" class="workflow-log" tabindex="0" role="region" aria-label="Setup log output"></pre></div><div class="workflow-footer"><p id="workflowFooterNote" class="workflow-small"></p><div class="modalactions"><button id="workflowExit" class="btn secondary" type="button">Exit Setup</button><div class="workflow-buttons"><button id="workflowViewLogs" class="btn secondary" type="button">View Logs</button><button id="workflowBack" class="btn secondary" type="button">Back</button><button id="workflowNext" class="btn" type="button">Next</button></div></div></div></div>';
    document.body.appendChild(modal);
    var passwordModal = document.createElement('div'); passwordModal.id = 'workflowPasswordModal'; passwordModal.className = 'modalback'; passwordModal.setAttribute('aria-hidden', 'true');
    passwordModal.innerHTML = '<div class="modalbox" role="dialog" aria-modal="true" aria-labelledby="workflowPasswordTitle"><h2 id="workflowPasswordTitle">Confirm with DSM</h2><p id="workflowPasswordMessage" class="muted"></p><p class="workflow-small">Enter the password for your current DSM administrator session. It is sent directly to DSM and cleared immediately. It is not saved in SadlerACME or a backup.</p><form id="workflowPasswordForm"><label for="workflowPassword">DSM administrator password</label><input id="workflowPassword" type="password" autocomplete="current-password" required><div class="modalactions"><button id="workflowPasswordCancel" class="btn secondary" type="button">Cancel</button><button id="workflowPasswordSubmit" class="btn" type="submit">Confirm</button></div></form></div>';
    document.body.appendChild(passwordModal); bind(); status().catch(function () {});
    global.SadlerWorkflow = Object.assign(helpers, { openWizard: openWizard, refresh: status, acceptStatus: acceptStatus });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})(typeof window !== 'undefined' ? window : globalThis);
