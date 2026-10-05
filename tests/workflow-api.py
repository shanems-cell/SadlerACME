#!/usr/bin/env python3
"""Real authenticated CGI protocol tests; no network or DSM mutations."""
import copy,fcntl,hashlib,json,os,subprocess,unittest,time
import regression as fixtures

class WorkflowAPI(fixtures.Regression):
    def json_request(self,payload,env=None):
        body=json.dumps(payload)
        e=dict(self.env,REQUEST_METHOD='POST',CONTENT_TYPE='application/json',CONTENT_LENGTH=str(len(body)),QUERY_STRING='',**(env or {}))
        p=subprocess.run(['sh',str(self.cgi)],input=body,text=True,capture_output=True,env=e,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stderr,'',p.stderr)
        return p.stdout
    def post(self,action,**fields):
        return self.json_request(dict(action=action,csrf=self.csrf(),**fields))
    def response(self,raw):return json.loads(raw.split('\n\n',1)[1])
    def settings(self):return self.response(self.request(query='api=settings'))
    def test_settings_never_returns_token(self):
        d=self.settings();self.assertTrue(d['has_token']);self.assertNotIn('cf_token',d['config']);self.assertNotIn(fixtures.TOKEN,json.dumps(d));self.assertEqual(len(d['settings_hash']),64)
    def test_all_json_actions_require_admin_and_csrf(self):
        for action in ['wizard-test','wizard-apply','backup','restore','download-backup','automation-intent','save-auto']:
            with self.subTest(action=action):
                self.assertIn('403 Forbidden',self.json_request(dict(action=action,csrf='bad')))
                self.assertIn('401 Unauthorized',self.json_request(dict(action=action,csrf=self.csrf()),env={'TEST_USER':''}))
    def test_draft_test_is_immutable_and_never_saves_settings(self):
        before=(self.etc/'settings.json').read_bytes();draft=copy.deepcopy(fixtures.CONFIG);draft['domains']=['new.example.com'];draft['cf_token']=''
        d=self.response(self.post('wizard-test',config=draft));self.assertTrue(d['ok'])
        job=json.loads((self.inbox/d['job_id']).read_text());self.assertEqual(job['config']['domains'],['new.example.com']);self.assertEqual(job['config']['cf_token'],fixtures.TOKEN)
        self.assertEqual((self.etc/'settings.json').read_bytes(),before)
    def test_invalid_draft_never_queues_or_saves(self):
        d=copy.deepcopy(fixtures.CONFIG);d['domains']=['example.com; touch /tmp/pwned']
        r=self.post('wizard-apply',config=d,expected_settings_hash=self.settings()['settings_hash']);self.assertIn('400 Bad Request',r);self.assertFalse(list(self.inbox.glob('*.job')))
    def test_restore_accepts_token_only_and_settings_only_document(self):
        r=self.post('restore',config={'cf_token':fixtures.TOKEN},backup={'format':'SadlerACME','version':1,'settings':{'email':'','domains':[]}},expected_settings_hash=self.settings()['settings_hash'])
        self.assertTrue(self.response(r)['ok']) # Full recovery validation is the root worker's job.
        r=self.post('restore',config={'cf_token':''},backup={});self.assertIn('400 Bad Request',r)
    def test_unavailable_worker_rejected_before_job_or_configuration_change(self):
        before=(self.etc/'settings.json').read_bytes()
        held=self.inbox.with_name('inbox-held');self.inbox.rename(held)
        for action,fields in [('restore',{'config':{'cf_token':fixtures.TOKEN},'backup':{'format':'SadlerACME','version':1,'settings':{}}}),('wizard-test',{'config':fixtures.CONFIG}),('finish-setup',{})]:
            with self.subTest(action=action):
                raw=self.post(action,**fields)
                self.assertIn('409 Conflict',raw)
                response=self.response(raw)
                self.assertFalse(response['ok']);self.assertEqual(response['code'],'worker_unavailable')
                self.assertNotIn('job_id',response);self.assertNotIn(fixtures.TOKEN,raw)
                self.assertFalse(self.inbox.exists());self.assertFalse(list(held.glob('*.job')))
                self.assertEqual((self.etc/'settings.json').read_bytes(),before)
        held.rename(self.inbox)
        response=self.response(self.post('restore',config={'cf_token':fixtures.TOKEN},backup={'format':'SadlerACME','version':1,'settings':{}}))
        self.assertTrue(response['ok']);self.assertEqual(len(list(self.inbox.glob('*.job'))),1)
    def test_other_rejections_do_not_claim_worker_recovery(self):
        for i in range(5):(self.inbox/f'{i:012}-aaaa.job').write_text('{}')
        full=self.response(self.post('refresh'))
        self.assertIn('Five jobs',full['message']);self.assertNotIn('code',full)
        stopped=self.var/'package.running';stopped.unlink()
        response=self.response(self.post('refresh'))
        self.assertEqual(response['message'],'Package is stopped');self.assertNotIn('code',response)
        response=self.response(self.json_request({'action':'refresh','csrf':'invalid'}))
        self.assertIn('Security token',response['message']);self.assertNotIn('code',response)
    def test_configuration_lock_blocks_manual_save_and_auto(self):
        lock=self.status/'configuration.lock';lock.touch();f=lock.open();self.addCleanup(f.close);fcntl.flock(f,fcntl.LOCK_EX)
        r=self.post('save-auto',auto_renew='0',expected_settings_hash=self.settings()['settings_hash']);self.assertIn('409 Conflict',r)
        r=self.request(dict(action='save',csrf=self.csrf(),**dict(fixtures.CONFIG,domains='example.com')));self.assertIn('configuration operation is running',r)
    def test_prepared_uninstall_is_not_classified_as_worker_expiry(self):
        before=(self.etc/'settings.json').read_bytes()
        (self.status/'uninstall_ready').write_text('yes')
        self.inbox.rmdir()
        raw=self.post('refresh');response=self.response(raw)
        self.assertIn('409 Conflict',raw)
        self.assertIn('Uninstall is prepared',response['message'])
        self.assertNotIn('code',response);self.assertNotIn('job_id',response)
        self.assertEqual((self.etc/'settings.json').read_bytes(),before)
    def test_auto_change_checks_hash_and_permanent_state(self):
        h=self.settings()['settings_hash'];self.assertIn('409 Conflict',self.post('save-auto',auto_renew='1',expected_settings_hash=h))
        (self.status/'scheduler_status').write_text('Installed and enabled');(self.status/'setup_temporary').write_text('no')
        self.assertTrue(self.response(self.post('save-auto',auto_renew='0',expected_settings_hash=h))['ok'])
        self.assertEqual(json.loads((self.etc/'settings.json').read_text())['auto_renew'],'0')
        self.assertIn('409 Conflict',self.post('save-auto',auto_renew='1',expected_settings_hash=h))
    def test_auto_save_queues_only_status_refresh_with_committed_settings(self):
        (self.status/'scheduler_status').write_text('Installed and enabled')
        (self.status/'applied_signature').write_text(self.shell('config_signature').stdout.strip())
        calls=self.root/'systemctl-calls'
        for auto in ('0','1'):
            with self.subTest(auto=auto):
                for p in self.inbox.glob('*.job'):p.unlink()
                raw=self.json_request(dict(action='save-auto',csrf=self.csrf(),auto_renew=auto,expected_settings_hash=self.settings()['settings_hash']),env={'TEST_SYSTEMCTL_LOG':str(calls)})
                response=self.response(raw)
                self.assertTrue(response['ok']);self.assertTrue(response['status_refresh_queued'])
                jobs=list(self.inbox.glob('*.job'));self.assertEqual(len(jobs),1)
                queued=json.loads(jobs[0].read_text())
                self.assertEqual(queued['action'],'refresh')
                self.assertEqual(queued['config']['auto_renew'],auto)
                self.assertEqual(jobs[0].stat().st_mode & 0o777,0o600)
                self.assertNotIn(fixtures.TOKEN,raw)
        self.assertFalse(calls.exists(),'The CGI must not restart a timer or run privileged service commands')
    def test_auto_save_succeeds_if_status_refresh_cannot_be_queued(self):
        for i in range(5):(self.inbox/f'{i:012}-aaaa.job').write_text('{}')
        response=self.response(self.post('save-auto',auto_renew='0',expected_settings_hash=self.settings()['settings_hash']))
        self.assertTrue(response['ok']);self.assertFalse(response['status_refresh_queued'])
        self.assertIn('saved',response['message']);self.assertIn('Status refresh is pending',response['message'])
        self.assertEqual(json.loads((self.etc/'settings.json').read_text())['auto_renew'],'0')
        self.assertEqual(len(list(self.inbox.glob('*.job'))),5)
    def test_download_requires_valid_fresh_fixed_path_and_queues_deletion(self):
        folder=self.protected/'transfers';folder.mkdir();transfer='012abc-345def';f=folder/(transfer+'.json');f.write_text('{"format":"SadlerACME","test":true}')
        for invalid in ['../../settings','zzzz','abc/def','']:
            self.assertIn('400 Bad Request',self.post('download-backup',transfer_id=invalid))
        r=self.post('download-backup',transfer_id=transfer);self.assertIn('Content-Disposition: attachment',r);self.assertEqual(self.response(r)['format'],'SadlerACME')
        jobs=[json.loads(p.read_text()) for p in self.inbox.glob('*.job')];self.assertTrue(any(j['action']=='backup-delete' and j['transfer_id']==transfer for j in jobs))
        os.utime(f,(time.time()-901,time.time()-901));self.assertIn('410 Gone',self.post('download-backup',transfer_id=transfer))
        f.unlink();f.symlink_to(self.etc/'settings.json');self.assertIn('410 Gone',self.post('download-backup',transfer_id=transfer))
    def test_enabling_auto_requires_applied_matching_recovered_profile(self):
        h=self.settings()['settings_hash']
        (self.status/'scheduler_status').write_text('Installed and enabled')
        self.assertIn('409 Conflict',self.post('save-auto',auto_renew='1',expected_settings_hash=h))
        (self.status/'applied_signature').write_text(self.shell('config_signature').stdout.strip())
        for guard in ['wizard_apply_pending','restore_requires_issue']:
            (self.status/guard).write_text('yes')
            self.assertIn('409 Conflict',self.post('save-auto',auto_renew='1',expected_settings_hash=h))
            (self.status/guard).write_text('no')
        self.assertTrue(self.response(self.post('save-auto',auto_renew='1',expected_settings_hash=h))['ok'])
    def test_job_receipts_survive_other_job_completion(self):
        folder=self.status/'jobs';folder.mkdir();job='123-abc.job';(folder/(job+'.json')).write_text(json.dumps({'ok':True,'job_id':job,'result':'completed','message':'done'}))
        (self.status/'last_job').write_text('another.job')
        self.assertEqual(self.response(self.request(query='api=job&id='+job))['result'],'completed')
        self.assertEqual(self.response(self.request(query='api=job&id=987-cba.job'))['result'],'pending')
        self.assertIn('400 Bad Request',self.request(query='api=job&id=../../settings.json'))
    def test_automation_intent_is_explicit_and_authenticated(self):
        self.assertFalse((self.var/'automation.requested').exists());self.assertTrue(self.response(self.post('automation-intent'))['ok']);self.assertTrue((self.var/'automation.requested').exists())
    def test_large_non_restore_payload_rejected(self):
        self.assertIn('413 Payload Too Large',self.post('wizard-test',padding='x'*32768))
    def test_saved_domain_change_reports_pending(self):
        signature=self.shell('config_signature').stdout.strip();(self.status/'applied_signature').write_text(signature)
        cfg=copy.deepcopy(fixtures.CONFIG);cfg['domains']=['new.example.com'];(self.etc/'settings.json').write_text(json.dumps(cfg))
        self.assertEqual(self.response(self.request(query='api=status'))['settings_pending'],'yes')

def load_tests(loader,tests,pattern):return unittest.TestSuite(WorkflowAPI(n) for n in sorted(WorkflowAPI.__dict__) if n.startswith('test_'))
if __name__=='__main__':unittest.main(verbosity=2)
