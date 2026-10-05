/* Execute the rendered dashboard's event handlers without network access.
 * DSM and DOM objects are fixtures; this is not a real DSM/browser test. */
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map(), requests = [], messages = [], windowEvents = {}, timers = new Map();
const tabs = [], panes = [], stored = new Map(Object.entries(input.storage || {}));
let clockShift = 0, timerId = 0, statusIndex = 0, receiptIndex = 0;
class FixtureDate extends Date {
  static now(){return (input.browserEpoch ? Number(input.browserEpoch) * 1000 : Date.now()) + clockShift;}
}
function node(id) {
  if (!nodes.has(id)) {
    const element = {
      id, value: '', textContent: '', className: '', hidden: false, disabled: false,
      style: {}, events: {}, attributes: {},
      addEventListener(event, callback){this.events[event] = callback;},
      getAttribute(name){return name === 'class' ? this.className : this.attributes[name] ?? null;},
      setAttribute(name, value){if(name === 'class')this.className = String(value);else this.attributes[name] = String(value);},
      removeAttribute(name){delete this.attributes[name];},
      click(){if(!this.disabled && this.events.click)this.events.click.call(this, {target:this, preventDefault(){}});},
      focus(){},
      querySelector(selector){return selector === '[name=csrf]' ? {value: input.csrf} : node(id + '-child');},
      querySelectorAll(){return [];}
    };
    element.classList = {
      contains(value){return element.className.split(/\s+/).includes(value);},
      add(value){this.toggle(value, true);}, remove(value){this.toggle(value, false);},
      toggle(value, force){const classes = new Set(element.className.split(/\s+/).filter(Boolean));
        const add = force === undefined ? !classes.has(value) : force;
        if(add)classes.add(value);else classes.delete(value);
        element.className = [...classes].join(' ');return add;}
    };
    nodes.set(id, element);
  }
  return nodes.get(id);
}
// Parse only the rendered attributes needed by these event-handler fixtures.
// This does not replace browser layout or accessibility-tree testing.
for (const match of (input.html || '').matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
  const attrs = Object.fromEntries([...match[2].matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
  const classes = (attrs.class || '').split(/\s+/);
  const id = attrs.id || (attrs['data-tab'] ? 'navigation-' + attrs['data-tab'] : classes.includes('wrap') ? 'app-wrap' : '');
  if(!id)continue;
  const element = node(id);element.attributes = attrs;element.className = attrs.class || '';
  element.hidden = /(?:^|\s)hidden(?:\s|$|=)/.test(match[2]);
  if(classes.includes('tabbtn'))tabs.push(element);
  if(classes.includes('tabpane'))panes.push(element);
}
for (const [id, attrs] of Object.entries(input.attributes || {})) Object.assign(node(id).attributes, attrs);
const action = node('action-form');
action.fields = {action: 'check', csrf: input.csrf};
node('schedulerStatusForm').fields = {action: 'scheduler-status', csrf: input.csrf};
node('schedulerMode').value = 'set';
node('schedAdminPass').value = 'offline-fixture-password';
const parent = {postMessage(message){messages.push(message);}};
const context = {
  URLSearchParams, Date: FixtureDate, Promise,
  window: {
    location: {search: '?SynoToken=offline-dsm-token', origin: 'https://nas.invalid'}, parent,
    innerWidth: Number(input.windowWidth || 1024),
    addEventListener(event, callback){windowEvents[event] = callback;}
  },
  document: {
    hidden: false, getElementById: node,
    querySelectorAll(selector){return selector === '.actionForm' ? [action] : selector === '.tabbtn' ? tabs : selector === '.tabpane' ? panes : [];},
    querySelector(selector){if(selector === '.wrap')return node('app-wrap');
      const match = selector.match(/^\.tabbtn\[data-tab="([^"]+)"\]$/);
      return match ? tabs.find(tab => tab.getAttribute('data-tab') === match[1]) || null : null;},
    addEventListener(){}
  },
  sessionStorage: {
    getItem(key){if(input.storageDisabled)throw new Error('Storage unavailable');return stored.get(key) || null;},
    setItem(key,value){if(input.storageDisabled)throw new Error('Storage unavailable');stored.set(key,String(value));}
  },
  FormData: class {
    constructor(form){this.fields = Object.entries(form.fields || {});}
    [Symbol.iterator](){return this.fields[Symbol.iterator]();}
  },
  confirm(){return true;},
  setTimeout(callback, delay){timers.set(++timerId,{callback,delay});return timerId;},
  clearTimeout(id){timers.delete(id);},
  fetch(url, options){
    const item = {url, method: options.method || 'GET', credentials: options.credentials,
      body: options.body ? Object.fromEntries(options.body) : null};
    requests.push(item);
    const params = new URLSearchParams(url.split('?')[1] || '');
    if(item.method === 'GET' && params.get('api') === 'job') {
      const receipt = (input.jobReceipts || [])[receiptIndex++];
      if(receipt)return Promise.resolve({ok:true,json:() => Promise.resolve(receipt)});
      return new Promise(() => {});
    }
    // Legacy callers resolve one status poll and leave later actions pending.
    const statuses = input.statusPolls || [input.status || {}];
    if(item.method === 'GET' && statusIndex < statuses.length) {
      const status = statuses[statusIndex++];
      if(status.fetchError)return Promise.reject(new Error(status.fetchError));
      return Promise.resolve({ok: true, json: () => Promise.resolve({state: 'idle', checked_epoch: 0, ...status})});
    }
    if(item.body && item.body.action === 'refresh' && input.refreshFailure) {
      return Promise.resolve({ok:false, status:503,
        text:() => Promise.resolve(JSON.stringify({ok:false,message:input.refreshFailure}))});
    }
    if(item.body && item.body.action === 'refresh' && input.refreshJobId) {
      return Promise.resolve({ok:true,text:() => Promise.resolve(JSON.stringify({ok:true,job_id:input.refreshJobId}))});
    }
    return new Promise(() => {});
  }
};
for (const [id, value] of Object.entries(input.initialText || {})) node(id).textContent = value;
vm.runInNewContext(input.script, context);
function assertText(expected, phase) {
  for(const [id,value] of Object.entries(expected || {})) assert.strictEqual(node(id).textContent,value,`${id}: ${phase}`);
}
assertText(input.expectedInitialText, 'initial render');
if (input.expectedInitialNextText !== undefined) {
  assert.strictEqual(node('nextAuto').textContent, input.expectedInitialNextText, 'initial nextAuto text is incorrect');
}
if (input.expectedInitialNextEpoch !== undefined) {
  assert.strictEqual(node('nextAuto').textContent, new Date(Number(input.expectedInitialNextEpoch) * 1000).toLocaleString(),
    'initial nextAuto did not format the enabled schedule');
}
setImmediate(async () => {
  assertText(input.expectedText, 'first status poll');
  for(const [id,value] of Object.entries(input.expectedDisabled || {})) assert.strictEqual(node(id).disabled,value,`${id}: disabled`);
  if (input.expectedNextEpoch !== undefined) {
    assert.strictEqual(node('nextAuto').textContent, new Date(Number(input.expectedNextEpoch) * 1000).toLocaleString(),
      'nextAuto did not format the enabled schedule from the status poll');
  }
  if(input.navigation) {
    const toggle = node('menuToggle'), nav = node('appNavigation'), wrap = node('app-wrap');
    const selected = () => tabs.filter(tab => tab.getAttribute('aria-current') === 'page').map(tab => tab.getAttribute('data-tab'));
    const selectedPane = () => panes.filter(pane => pane.classList.contains('active')).map(pane => pane.id);
    assert.strictEqual(toggle.getAttribute('aria-controls'), nav.id);
    assert.strictEqual(toggle.getAttribute('aria-expanded'), 'false', 'compact navigation must start closed');
    assert.strictEqual(nav.hidden, false, 'wide navigation stays in the document and is controlled responsively by CSS');
    assert.strictEqual(wrap.classList.contains('menu-open'), false);
    assert.deepStrictEqual(selected(), [input.navigation.initialPage || 'dashboard']);
    const page = input.navigation.page || 'settings';
    tabs.find(tab => tab.getAttribute('data-tab') === page).click();
    assert.deepStrictEqual(selected(), [page]);assert.deepStrictEqual(selectedPane(), ['tab-' + page]);
    toggle.click();
    assert.strictEqual(toggle.getAttribute('aria-expanded'), 'true');
    assert.strictEqual(wrap.classList.contains('menu-open'), true);
    assert.deepStrictEqual(selected(), [page]);assert.deepStrictEqual(selectedPane(), ['tab-' + page]);
    if(Number(input.windowWidth || 1024) <= 820) {
      const compactPage = input.navigation.compactPage || 'automation';
      tabs.find(tab => tab.getAttribute('data-tab') === compactPage).click();
      assert.deepStrictEqual(selected(), [compactPage]);assert.deepStrictEqual(selectedPane(), ['tab-' + compactPage]);
      assert.strictEqual(toggle.getAttribute('aria-expanded'), 'false', 'compact menu closes after choosing a page');
      assert.strictEqual(wrap.classList.contains('menu-open'), false);
      toggle.click();
      assert.strictEqual(toggle.getAttribute('aria-expanded'), 'true');assert.strictEqual(wrap.classList.contains('menu-open'), true);
    }
    node('viewLogBtn').click();
    assert.deepStrictEqual(selected(), ['logs']);
    if(Number(input.windowWidth || 1024) <= 820) {
      assert.strictEqual(toggle.getAttribute('aria-expanded'), 'false');assert.strictEqual(wrap.classList.contains('menu-open'), false);
    }
    assert.deepStrictEqual(selectedPane(), ['tab-logs']);
    if(!input.storageDisabled)assert.strictEqual(stored.get('sadleracme.tab'),'logs');
  }
  for(const step of input.steps || []) {
    clockShift += step.advanceMs || 0;
    if(step.poll) {
      const scheduled = [...timers].find(([,value]) => value.delay === 10000 || value.delay === 2000);
      assert(scheduled, 'expected a scheduled status poll');
      timers.delete(scheduled[0]);scheduled[1].callback();
    }
    if(step.refresh)node('statusRefreshBtn').click();
    await new Promise(resolve => setImmediate(resolve));
    assertText(step.expectedText, 'subsequent status poll');
    for(const [id,value] of Object.entries(step.expectedDisabled || {})) assert.strictEqual(node(id).disabled,value,`${id}: disabled`);
  }
  if(input.exerciseActions === false){process.stdout.write(JSON.stringify(requests));return;}
  const event = {preventDefault(){}};
  action.events.submit(event);
  node('schedulerStatusForm').events.submit(event);
  node('clearLog').events.click();
  node('schedulerInstallForm').events.submit(event);
  windowEvents.message({origin: 'https://nas.invalid', source: parent,
    data: {type: 'sadleracme.scheduler.result', requestId: messages[0].requestId, ok: true}});
  process.stdout.write(JSON.stringify(requests));
});
