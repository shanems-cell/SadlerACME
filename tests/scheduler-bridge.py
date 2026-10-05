#!/usr/bin/env python3
"""Run the desktop scheduler bridge against a stateful DSM API fixture.

The bridge itself is executed in Node's VM. These tests prove guards and request
ordering, not DSM acceptance. The event list/get fixture follows the read-only
DSM 7.4.1 response captured during earlier wizard testing. Temporary task
creation/run and token reuse still require NAS validation.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
BOOT = 'SadlerACME Bootstrap'
SETUP = 'SadlerACME Setup'
BOOT_CMD = '/bin/systemctl start pkg-sadleracme-bootstrap.service'
SETUP_CMD = '/bin/systemctl start pkg-sadleracme-setup.service'


def task(name=BOOT, **changes):
    value = dict(name=name, id=10 if name == BOOT else 11, owner='root',
                 real_owner='root', operation=BOOT_CMD if name == BOOT else SETUP_CMD,
                 event='bootup', operation_type='script', enable=name == BOOT)
    value.update(changes)
    return value


HARNESS = r'''
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let tasks = input.tasks || [], calls = [], results = [], definitions = {}, listCount = 0, deletionCount = 0;
let sent = {type:'sadleracme.scheduler.install',requestId:'fixture-1',mode:input.mode||'setup',password:input.password||''};
const frameWindow = {postMessage:(message,origin)=>results.push(JSON.parse(JSON.stringify(message)))};
const windowObject = {location:{origin:'https://nas.test'}, addEventListener:()=>{},removeEventListener:()=>{}};
const self = {callParent:()=>{}, sendWebAPI:function(request) {
  calls.push({api:request.api,method:request.method,version:request.version,params:JSON.parse(JSON.stringify(request.params))});
  const callback = (ok, value) => request.callback(ok,value);
  if (input.hold && calls.length === 1) return;
  if (request.method === 'list') {
    listCount++;
    if (input.failList) return callback(false,{});
    if (input.malformedList) return callback(true,{data:{tasks:[],total:'0'}});
    if (input.changeBeforeCommit && listCount === 2) tasks.push({name:'SadlerACME Setup',id:11,owner:'root',real_owner:'root',operation:'/bin/systemctl start pkg-sadleracme-setup.service',operation_type:'script',event:'bootup',enable:false});
    let rows = tasks.slice(request.params.offset, request.params.offset+request.params.limit);
    if (input.eventSummary) rows = rows.map(t=>({
      // Observed event_script list shape: no real_owner, operation or event.
      action:'Localised display text', can_delete:true, can_edit:true, can_run:true,
      enable:t.enable, id:t.name==='SadlerACME Bootstrap'?1000:1001,
      name:t.name, next_trigger_time:'', owner:t.owner==='root'||typeof t.owner==='object'?'root':t.owner,
      type:input.summaryType||'event_script'
    }));
    else if (input.summaryOnly) rows = rows.map(t=>({id:t.id,name:t.name,real_owner:t.real_owner,owner:t.owner,enable:t.enable}));
    return callback(true,{success:true,data:{tasks:rows,total:tasks.length}});
  }
  if (request.method === 'get') {
    if (input.eventSummary && request.api !== 'SYNO.Core.EventScheduler') throw Error('Event summary used wrong API');
    if (request.api === 'SYNO.Core.EventScheduler') {
      if (request.version !== 1 || Object.keys(request.params).join(',') !== 'task_name') throw Error('Unexpected event detail request');
      if (input.eventGetFail) return callback(false,{});
      if (input.eventGetRejected) return callback(true,{success:false,error:{code:999}});
      const t=tasks.find(t=>t.name===request.params.task_name);
      if (!t) return callback(false,{});
      // Observed full event-task shape, including the root UID/name map.
      const data={depend_on_task:'',description:'',enable:t.enable,event:t.event,
        extra:{},last_exit_info:{exit_code:0,exit_type:'normal'},operation:t.operation,
        operation_type:t.operation_type,owner:t.owner==='root'?{'0':'root'}:t.owner,
        run_the_same_time:false,status:{running:[]},task_name:t.name};
      Object.assign(data,input.eventDetailOverrides||{});
      (input.omitEventFields||[]).forEach(key=>delete data[key]);
      return callback(true,input.unwrappedEventDetail?data:{success:true,httpd_restart:false,data:data});
    }
    if (input.badDetail) return callback(true,{data:{name:'SadlerACME Bootstrap',enable:true}});
    return callback(true,{data:tasks.find(t=>t.id===request.params.id)});
  }
  if (request.api === 'SYNO.Core.User.PasswordConfirm') {
    if (input.authFail) return callback(false,{});
    return callback(true,{data:{SynoConfirmPWToken: input.noToken?'':'FIXTURE_TOKEN'}});
  }
  if (request.method === 'create' || request.method === 'set') {
    if (input.saveFail) return callback(false,{});
    if (!input.dontPersist) {
      tasks = tasks.filter(t=>t.name !== request.params.task_name);
      tasks.push({name:request.params.task_name,id:request.params.task_name==='SadlerACME Setup'?11:10,real_owner:'root',owner:request.params.owner,enable:request.params.enable,event:request.params.event,operation:request.params.operation,operation_type:request.params.operation_type});
    }
    return callback(true,{});
  }
  if (request.method === 'delete') {
    deletionCount++;
    if (input.secondDeleteFails && deletionCount === 2) return callback(false,{});
    if (!input.dontDelete) tasks=tasks.filter(t=>t.name!==request.params.task_name);
    return callback(true,{});
  }
  if (request.method === 'run') return callback(!input.runFail,{});
  throw Error('Unexpected API '+request.api+' '+request.method);
}};
const ctx = {window:windowObject,document:{getElementById:()=>({contentWindow:frameWindow})},
  SYNO:{SDS:{Session:{SynoToken:'SESSION_TOKEN'}}},
  Ext:{ns:()=>{},define:(name,spec)=>definitions[name]=spec,id:()=> 'fixture-frame',apply:(a,b)=>Object.assign(a,b),urlAppend:x=>x}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
definitions['SYNO.SDS.SadlerACME.MainWindow'].constructor.call(self,{});
let event = {data:sent,origin:input.foreignOrigin?'https://other.test':'https://nas.test',source:input.foreignFrame?{}:frameWindow};
self._schedulerBridgeHandler(event);
if (input.hold) self._schedulerBridgeHandler({data:{type:sent.type,requestId:'fixture-1',mode:'setup'},origin:'https://nas.test',source:frameWindow});
process.stdout.write(JSON.stringify({calls,results,tasks,clearedPassword:sent.password==='',active:self._schedulerBridgeRequest}));
'''


@unittest.skipUnless(NODE, 'Node.js is required to execute desktop bridge fixtures')
class Bridge(unittest.TestCase):
    def run_case(self, **config):
        proc = subprocess.run([NODE, '-e', HARNESS, str(ROOT/'src/ui/SadlerACME.js')],
                              input=json.dumps(config), text=True, capture_output=True, check=True)
        return json.loads(proc.stdout)

    @staticmethod
    def mutations(result):
        return [c for c in result['calls'] if c['method'] in ('create','set','delete','run')]

    def test_foreign_origin_and_foreign_frame_are_ignored(self):
        for option in ('foreignOrigin', 'foreignFrame'):
            result = self.run_case(password='secret', **{option: True})
            self.assertEqual(result['calls'], [])
            self.assertEqual(result['results'], [])

    def test_unknown_mode_is_ignored_and_secret_cleared(self):
        result = self.run_case(mode='execute-anything', password='secret')
        self.assertEqual(result['calls'], [])
        self.assertTrue(result['clearedPassword'])

    def test_missing_task_prompts_before_auth_or_mutation(self):
        result = self.run_case()
        self.assertTrue(result['results'][0]['needsPassword'])
        self.assertEqual(self.mutations(result), [])
        self.assertEqual([c['method'] for c in result['calls']], ['list'])

    def test_existing_permanent_is_reused_without_password(self):
        result = self.run_case(tasks=[task()])
        self.assertTrue(result['results'][0]['ok'])
        self.assertTrue(result['results'][0]['reused'])
        self.assertFalse(result['results'][0]['temporary'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','run'])

    def test_temporary_setup_is_disabled_and_verified_before_running(self):
        result = self.run_case(password='secret')
        self.assertTrue(result['results'][0]['ok'])
        calls = result['calls']
        self.assertEqual([c['method'] for c in calls], ['list','auth','list','create','list','run'])
        create = next(c for c in calls if c['method']=='create')
        self.assertEqual(create['params']['task_name'], SETUP)
        self.assertEqual(create['params']['operation'], SETUP_CMD)
        self.assertIs(create['params']['enable'], False)
        self.assertEqual(create['params']['owner'], {'0':'root'})
        for call in calls:
            if call['method'] != 'auth': self.assertNotIn('secret',json.dumps(call))
        self.assertTrue(result['clearedPassword'])

    def test_existing_disabled_temporary_is_reused_without_password(self):
        result = self.run_case(tasks=[task(SETUP)])
        self.assertTrue(result['results'][0]['temporary'])
        self.assertTrue(result['results'][0]['reused'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','run'])

    def test_enabled_or_unexpected_temporary_is_not_run(self):
        for changes in ({'enable':True},{'operation':'echo other'},{'owner':'somebody'},{'event':'shutdown'}):
            result = self.run_case(tasks=[task(SETUP,**changes)],password='secret')
            self.assertFalse(result['results'][0]['ok'])
            self.assertEqual(self.mutations(result), [])

    def test_disabled_permanent_requires_explicit_correction(self):
        result = self.run_case(tasks=[task(enable=False)],password='secret')
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual(self.mutations(result), [])

    def test_duplicate_name_fails_closed(self):
        for name in (BOOT, SETUP):
            result = self.run_case(tasks=[task(name),task(name,id=12)],password='secret')
            self.assertFalse(result['results'][0]['ok'])
            self.assertEqual(self.mutations(result), [])
            self.assertIn('duplicates',result['results'][0]['message'])

    def test_all_inventory_pages_checked_for_duplicates(self):
        tasks = [dict(name='Other '+str(i),id=100+i) for i in range(201)]
        result = self.run_case(tasks=[task()]+tasks+[task(id=15)],password='secret')
        self.assertEqual([c['params']['offset'] for c in result['calls']], [0,200])
        self.assertEqual(self.mutations(result), [])
        self.assertFalse(result['results'][0]['ok'])

    def test_unknown_inventory_and_details_block_new_modes(self):
        for options in ({'failList':True},{'malformedList':True},{'summaryOnly':True,'badDetail':True,'tasks':[task()]}):
            result = self.run_case(password='secret',**options)
            self.assertFalse(result['results'][0]['ok'])
            self.assertEqual(self.mutations(result), [])

    def test_summary_inventory_fetches_full_details(self):
        result = self.run_case(tasks=[task()],summaryOnly=True)
        self.assertTrue(result['results'][0]['ok'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','get','run'])

    def test_observed_event_summary_reuses_bootstrap_without_password_or_mutation(self):
        result = self.run_case(tasks=[task()], eventSummary=True)
        self.assertTrue(result['results'][0]['ok'])
        self.assertTrue(result['results'][0]['reused'])
        self.assertFalse(result['results'][0]['temporary'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','get','run'])
        get = result['calls'][1]
        self.assertEqual((get['api'],get['version'],get['params']),
                         ('SYNO.Core.EventScheduler',1,{'task_name':BOOT}))
        self.assertEqual([c['method'] for c in self.mutations(result)], ['run'])

    def test_observed_event_detail_accepts_desktop_unwrapped_data(self):
        result = self.run_case(tasks=[task()], eventSummary=True, unwrappedEventDetail=True)
        self.assertTrue(result['results'][0]['ok'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','get','run'])

    def test_regular_summary_still_uses_original_detail_contract(self):
        result = self.run_case(tasks=[task()], summaryOnly=True)
        get = result['calls'][1]
        self.assertEqual((get['api'],get['version'],get['params']),
                         ('SYNO.Core.TaskScheduler',4,{'id':10,'real_owner':'root'}))
        self.assertTrue(result['results'][0]['ok'])

    def test_event_temporary_create_verifies_detail_before_run(self):
        result = self.run_case(eventSummary=True,password='secret')
        self.assertTrue(result['results'][0]['ok'])
        self.assertTrue(result['results'][0]['temporary'])
        self.assertTrue(result['results'][0]['created'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','auth','list','create','list','get','run'])
        create = next(c for c in result['calls'] if c['method']=='create')
        self.assertEqual(create['params']['task_name'],SETUP)
        self.assertEqual(create['params']['operation'],SETUP_CMD)
        self.assertIs(create['params']['enable'],False)

    def test_event_temporary_reuse_and_permanent_ensure(self):
        result = self.run_case(tasks=[task(SETUP)],eventSummary=True)
        self.assertTrue(result['results'][0]['temporary'])
        self.assertTrue(result['results'][0]['reused'])
        self.assertEqual([c['method'] for c in result['calls']], ['list','get','run'])
        for existing in ([],[task()],[task(enable=False)]):
            with self.subTest(existing=existing):
                result=self.run_case(mode='ensure',tasks=existing,eventSummary=True,password='secret')
                self.assertTrue(result['results'][0]['ok'])
                methods=[c['method'] for c in self.mutations(result)]
                self.assertEqual(methods, ['create','run'] if not existing else ['run'] if existing[0]['enable'] else ['set','run'])
                for get in (c for c in result['calls'] if c['method']=='get'):
                    self.assertEqual(get['api'],'SYNO.Core.EventScheduler')

    def test_event_task_cleanup_and_remove_verify_absence(self):
        for mode,names in (('cleanup-setup',[SETUP]),('remove-all',[BOOT,SETUP])):
            with self.subTest(mode=mode):
                result=self.run_case(mode=mode,tasks=[task(),task(SETUP)],eventSummary=True,password='secret')
                self.assertTrue(result['results'][0]['ok'])
                self.assertTrue(result['results'][0]['tasksAbsent'])
                self.assertEqual([c['params']['task_name'] for c in self.mutations(result)],names)
                self.assertNotIn('run',[c['method'] for c in result['calls']])
                self.assertEqual(result['calls'][-1]['method'],'get' if mode=='cleanup-setup' else 'list')

    def test_event_unknown_or_incomplete_detail_never_authorises_a_change(self):
        invalid=[{'task_name':'A different task'},{'owner':None},{'owner':{'0':'root','1':'other'}},
                 {'operation':None},{'operation_type':None},{'event':None},{'enable':'true'}]
        for override in invalid:
            for mode in ('setup','ensure','cleanup-setup','remove-all'):
                with self.subTest(override=override,mode=mode):
                    result=self.run_case(mode=mode,tasks=[task(),task(SETUP)],eventSummary=True,
                                         eventDetailOverrides=override,password='secret')
                    self.assertFalse(result['results'][0]['ok'])
                    self.assertEqual(self.mutations(result),[])
                    self.assertNotIn('auth',[c['method'] for c in result['calls']])
                    self.assertIn('Task ownership, command and trigger',result['results'][0]['message'])

    def test_event_unrecognised_values_not_run_or_deleted(self):
        for override in ({'owner':{'1000':'other'}},{'owner':'other'},
                         {'operation':'echo other'},{'operation_type':'service'},{'event':'shutdown'}):
            for mode in ('setup','cleanup-setup','remove-all'):
                with self.subTest(override=override,mode=mode):
                    result=self.run_case(mode=mode,tasks=[task(SETUP)],eventSummary=True,
                                         eventDetailOverrides=override,password='secret')
                    self.assertFalse(result['results'][0]['ok'])
                    self.assertEqual(self.mutations(result),[])
        for existing in (task(enable=False),task(SETUP,enable=True)):
            result=self.run_case(tasks=[existing],eventSummary=True,password='secret')
            self.assertFalse(result['results'][0]['ok'])
            self.assertEqual(self.mutations(result),[])

    def test_event_detail_missing_fields_do_not_use_display_action_or_summary_owner(self):
        for field in ('operation','owner','operation_type','event','enable'):
            with self.subTest(field=field):
                result=self.run_case(tasks=[task()],eventSummary=True,omitEventFields=[field],password='secret')
                self.assertFalse(result['results'][0]['ok'])
                self.assertEqual(self.mutations(result),[])

    def test_event_get_failures_are_actionable_and_do_not_mutate(self):
        for option in ('eventGetFail','eventGetRejected'):
            result=self.run_case(tasks=[task()],eventSummary=True,password='secret',**{option:True})
            self.assertFalse(result['results'][0]['ok'])
            self.assertEqual(self.mutations(result),[])
            self.assertIn('could not read the configuration of '+BOOT,result['results'][0]['message'])
            self.assertIn('Refresh DSM and retry',result['results'][0]['message'])

    def test_event_summary_unknown_type_does_not_guess_real_owner(self):
        result=self.run_case(tasks=[task()],eventSummary=True,summaryType='unknown',password='secret')
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual([c['method'] for c in result['calls']],['list'])
        self.assertEqual(self.mutations(result),[])

    def test_event_duplicate_names_stop_before_detail_or_mutation(self):
        result=self.run_case(tasks=[task(),task(id=12)],eventSummary=True,password='secret')
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual([c['method'] for c in result['calls']],['list'])
        self.assertEqual(self.mutations(result),[])

    def test_event_inventory_is_rechecked_after_password_confirmation(self):
        result=self.run_case(mode='ensure',tasks=[task(enable=False)],eventSummary=True,
                             password='secret',changeBeforeCommit=True)
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual(self.mutations(result),[])
        self.assertIn('changed while approval',result['results'][0]['message'])

    def test_failed_or_empty_password_approval_never_mutates(self):
        for option in ('authFail','noToken'):
            result=self.run_case(password='secret',**{option:True})
            self.assertTrue(result['results'][0]['needsPassword'])
            self.assertEqual(self.mutations(result), [])

    def test_task_change_during_password_confirmation_blocks_commit(self):
        result=self.run_case(password='secret',changeBeforeCommit=True)
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual(self.mutations(result), [])
        self.assertIn('changed while approval',result['results'][0]['message'])

    def test_create_acknowledgement_without_task_does_not_run(self):
        result=self.run_case(password='secret',dontPersist=True)
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual([c['method'] for c in self.mutations(result)], ['create'])

    def test_run_failure_reports_saved_task_for_cleanup(self):
        result=self.run_case(password='secret',runFail=True)
        self.assertFalse(result['results'][0]['ok'])
        self.assertTrue(result['results'][0]['taskSaved'])
        self.assertTrue(result['results'][0]['temporary'])

    def test_ensure_corrects_known_permanent_with_fresh_approval(self):
        result=self.run_case(mode='ensure',tasks=[task(enable=False)],password='secret')
        self.assertTrue(result['results'][0]['ok'])
        self.assertEqual([c['method'] for c in self.mutations(result)], ['set','run'])
        self.assertIs(result['tasks'][0]['enable'],True)

    def test_ensure_creates_only_after_verified_absence(self):
        result=self.run_case(mode='ensure',password='secret')
        self.assertTrue(result['results'][0]['ok'])
        self.assertEqual(result['tasks'][0]['name'],BOOT)
        self.assertEqual(result['tasks'][0]['operation'],BOOT_CMD)

    def test_cleanup_setup_never_deletes_permanent(self):
        result=self.run_case(mode='cleanup-setup',tasks=[task(),task(SETUP)],password='secret')
        self.assertTrue(result['results'][0]['ok'])
        self.assertTrue(result['results'][0]['tasksAbsent'])
        self.assertEqual([t['name'] for t in result['tasks']],[BOOT])

    def test_cleanup_never_deletes_unrecognised_command(self):
        result=self.run_case(mode='cleanup-setup',tasks=[task(SETUP,operation='echo other')],password='secret')
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual(self.mutations(result), [])

    def test_remove_all_requires_verified_absence_after_deletion(self):
        for dont_delete in (True,False):
            result=self.run_case(mode='remove-all',tasks=[task(),task(SETUP)],password='secret',dontDelete=dont_delete)
            self.assertEqual(result['results'][0]['ok'],not dont_delete)
            self.assertEqual([c['params']['task_name'] for c in self.mutations(result)], [BOOT,SETUP])

    def test_second_deletion_can_request_fresh_approval_without_recreating_first(self):
        result=self.run_case(mode='remove-all',tasks=[task(),task(SETUP)],password='secret',secondDeleteFails=True)
        self.assertTrue(result['results'][0]['needsPassword'])
        self.assertTrue(result['results'][0]['partial'])
        self.assertEqual([t['name'] for t in result['tasks']], [SETUP])
        retried=self.run_case(mode='remove-all',tasks=result['tasks'],password='new-secret')
        self.assertTrue(retried['results'][0]['ok'])
        self.assertEqual([c['method'] for c in self.mutations(retried)], ['delete'])

    def test_already_absent_cleanup_does_not_request_password(self):
        result=self.run_case(mode='cleanup-setup')
        self.assertTrue(result['results'][0]['tasksAbsent'])
        self.assertEqual([c['method'] for c in result['calls']],['list'])

    def test_concurrent_duplicate_request_cannot_clear_owner_lock(self):
        result=self.run_case(hold=True)
        self.assertEqual(result['active'],'fixture-1')
        self.assertEqual(len(result['calls']),1)
        self.assertFalse(result['results'][0]['ok'])

    def test_legacy_manual_actions_keep_tested_api_even_with_unknown_inventory(self):
        for mode in ('create','set','delete'):
            result=self.run_case(mode=mode,password='secret',failList=True)
            self.assertTrue(result['results'][0]['ok'])
            methods=[c['method'] for c in result['calls']]
            self.assertEqual(methods, ['auth',mode]+([] if mode=='delete' else ['run']))
            self.assertEqual(self.mutations(result)[0]['params']['task_name'],BOOT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
