#!/usr/bin/env python3
"""Offline regression checks. DSM paths are rewritten only in temporary copies.
No test contacts ACME/Cloudflare, runs a live DSM command, or modifies host DSM.
"""
import sys
import datetime, hashlib, json, os, re, shutil, subprocess, tempfile, unittest, fcntl, time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from assemble_worker import render_worker, render_cgi
TEST_CA_BUNDLE = None
TOKEN = 'test_cloudflare_token_01234567890123456789'
CONFIG = dict(email='admin@example.com', domains=['example.com', '*.example.com'], key_type='ec-384', cert_desc='SadlerACME wildcard', cf_token=TOKEN, default_on_create='0', auto_renew='1', dns_sleep='30')

def certificate(dest, *, expired=False, mismatch=False, domains=None):
    dest.mkdir(parents=True, exist_ok=True)
    now=datetime.datetime.now(datetime.timezone.utc)
    ca_key=ec.generate_private_key(ec.SECP384R1()); key=ec.generate_private_key(ec.SECP384R1())
    ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Offline test CA')])
    ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=3)).not_valid_after(now+datetime.timedelta(days=100)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(ca_key,hashes.SHA384()))
    cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'example.com')])).issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=2)).not_valid_after(now+datetime.timedelta(days=-1 if expired else 60)).add_extension(x509.SubjectAlternativeName([x509.DNSName(d) for d in (domains or CONFIG['domains'])]),critical=False).sign(ca_key,hashes.SHA384()))
    if mismatch: key=ec.generate_private_key(ec.SECP384R1())
    (dest/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()))
    (dest/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (dest/'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    if TEST_CA_BUNDLE is not None:
        with TEST_CA_BUNDLE.open('ab') as bundle:bundle.write(ca.public_bytes(serialization.Encoding.PEM))
    (dest/'fullchain.pem').write_bytes((dest/'cert.pem').read_bytes()+(dest/'ca.pem').read_bytes())

class Regression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='sadler-tests-'); self.addCleanup(self.tmp.cleanup)
        global TEST_CA_BUNDLE
        TEST_CA_BUNDLE=Path(self.tmp.name)/'trusted-ca.pem'
        self.root=Path(self.tmp.name); self.base=self.root/'var/packages/sadleracme'
        self.etc=self.base/'etc'; self.var=self.base/'var'; self.protected=self.root/'usr/local/etc/sadleracme'
        self.appdata=self.root/'volume1/@appdata/sadleracme'
        self.appconf=self.root/'volume1/@appconf/sadleracme'
        self.base.mkdir(parents=True)
        self.appdata.mkdir(parents=True); self.appconf.mkdir(parents=True)
        self.var.symlink_to(self.appdata); self.etc.symlink_to(self.appconf)
        self.private=self.protected/'private'; self.status=self.protected/'status'; self.inbox=self.protected/'inbox'
        self.bin=self.root/'mocks'; self.bin.mkdir()
        for p in (self.etc,self.var,self.private,self.status,self.inbox,self.root/'usr/syno/bin',self.root/'usr/local/etc/certificate'):
            p.mkdir(parents=True,exist_ok=True)
        os.chmod(self.private,0o700)
        (self.etc/'settings.json').write_text(json.dumps(CONFIG)); (self.var/'package.running').touch()
        (self.private/'work').mkdir(); (self.private/'work/config.json').write_text(json.dumps(CONFIG))
        self.write_exe(self.bin/'id', '#!/bin/sh\ncase "$1" in -u) echo 0;; -Gn) echo "${TEST_GROUPS:-administrators users}";; *) /usr/bin/id "$@";; esac\n')
        self.write_exe(self.bin/'systemctl','''#!/bin/sh
[ -z "${TEST_SYSTEMCTL_LOG:-}" ] || printf '%s\\n' "$*" >> "$TEST_SYSTEMCTL_LOG"
# Model the observed DSM systemd 219 option boundary. Enabling/disabling a
# unit is separate from starting/stopping it; newer --now must never slip in.
for arg in "$@"; do
  [ "$arg" != --now ] || { echo "systemctl: unrecognized option '--now'" >&2; exit 1; }
done
case "$1" in
  show)
    if [ -n "${TEST_SERVICE_UNIT:-}" ] && [ "$2" != "$TEST_SERVICE_UNIT" ]; then
      load=loaded; active=inactive; rc=0
    else
      load=${TEST_LOAD_STATE-loaded}; active=${TEST_SERVICE_STATE-inactive}; rc=${TEST_SHOW_RC:-0}
      [ -z "${TEST_SERVICE_STATE_FILE:-}" ] || active=$(cat "$TEST_SERVICE_STATE_FILE")
      if [ "${TEST_SHOW_REPORT+x}" = x ]; then printf '%s' "$TEST_SHOW_REPORT"; exit "$rc"; fi
    fi
    case "$*" in
      *--value*) printf '%s\\n' "$active";;
      *) printf 'LoadState=%s\\nActiveState=%s\\n' "$load" "$active";;
    esac
    exit "$rc";;
  is-active) echo "${TEST_SERVICE_STATE:-inactive}";;
  *) exit 0;;
esac
''')
        auth=self.root/'usr/syno/synoman/webman/modules/authenticate.cgi'
        self.write_exe(auth,'#!/bin/sh\nprintf "%s" "${TEST_USER-admin}"\n')
        self.listfile=self.root/'certificate-list.json';self.listfile.write_text(json.dumps({'success':True,'data':{'certificates':[]}}))
        self.write_exe(self.root/'usr/syno/bin/synowebapi',f'#!/bin/sh\ncase "$*" in *method=import*) echo \'{{"success":true}}\';; *) cat "{self.listfile}";; esac\n')
        self.write_exe(self.root/'usr/syno/bin/synow3tool','#!/bin/sh\nexit "${TEST_W3_RC:-0}"\n')
        self.write_exe(self.root/'usr/syno/bin/synopkg','#!/bin/sh\ncase "$1" in restart) exit "${TEST_RESTART_RC:-0}";; *) exit 0;; esac\n')
        self.write_exe(self.bin/'sqlite3','#!/bin/sh\n[ "${TEST_SQL_FAIL:-0}" = 0 ] || exit 1\nprintf "%s" "${TEST_SCHEDULER_ROW:-}"\n')
        db=self.root/'usr/syno/etc/esynoscheduler/esynoscheduler.db';db.parent.mkdir(parents=True);db.touch()
        self.worker=self.root/'worker.sh'; self.cgi=self.root/'index.cgi'
        self.worker.write_text(self.rewrite(render_worker(ROOT)))
        self.cgi.write_text(self.rewrite(render_cgi(ROOT)))
        self.functions=self.root/'functions.sh';self.functions.write_text(self.worker.read_text().split('# All entry points share')[0])
        self.env=dict(os.environ, TEST_USER='admin', SSL_CERT_FILE=str(TEST_CA_BUNDLE))
    def rewrite(self,text):
        text=re.sub(r'/var/packages|/usr/syno|/usr/local|/volume',lambda m:str(self.root)+m.group(),text)
        text=re.sub(r'^PATH=.*$',f'PATH={self.bin}:/usr/bin:/bin',text,flags=re.M)
        text=text.replace('while [ "$ps_parent" != / ]; do', 'while [ "$ps_parent" != "'+str(self.root)+'" ]; do')
        # Certificate trust checks stop at the fixture root; the host /tmp
        # ancestor is intentionally outside this synthetic DSM filesystem.
        text=text.replace('while [ "$checked" != / ]; do', 'while [ "$checked" != "'+str(self.root)+'" ]; do')
        return text
    def write_exe(self,path,text):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);path.chmod(0o755)
    def shell(self,code,expected=0,env=None):
        prefix=f'. "{self.functions}"\nWORK="$ROOT_STATE/work"\nCONFIG="$WORK/config.json"\n'
        p=subprocess.run(['sh','-c',prefix+code],text=True,capture_output=True,env=dict(self.env,**(env or {})),timeout=15)
        if expected is not None:self.assertEqual(p.returncode,expected,p.stderr+'\n'+p.stdout)
        return p
    def request(self,fields=None,env=None,query=''):
        body='' if fields is None else urlencode(fields)
        e=dict(self.env,REQUEST_METHOD='GET' if fields is None else 'POST',CONTENT_TYPE='application/x-www-form-urlencoded',CONTENT_LENGTH=str(len(body)),QUERY_STRING=query,**(env or {}))
        p=subprocess.run(['sh',str(self.cgi)],input=body,text=True,capture_output=True,env=e,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stderr,'',p.stderr)
        return p.stdout
    def csrf(self):
        self.request();return next(self.etc.glob('ui_csrf.*')).read_text()
    def job(self,action='refresh',config=None):
        fields=dict(action=action,csrf=self.csrf())
        text=self.request(fields); self.assertNotIn('Status: 409',text,text)
        return json.loads(text.split('\n\n',1)[1])['job_id']
    def full_worker(self,action='worker',env=None):
        return subprocess.run(['sh',str(self.worker),action],capture_output=True,text=True,env=dict(self.env,**(env or {})),timeout=15)
    def lifecycle_hook(self,name,env=None,args=(),timeout=15):
        # Exercise preupgrade's real preinst dependency, including prerequisites.
        for hook in set((name,'preinst')):
            (self.root/hook).write_text(self.rewrite((ROOT/'pkg/scripts'/hook).read_text()))
        return subprocess.run(['sh',str(self.root/name),*args],capture_output=True,text=True,
                              env=dict(self.env,PATH=f'{self.bin}:/usr/bin:/bin',**(env or {})),timeout=timeout)
    def set_list(self,certs,success=True):
        self.listfile.write_text(json.dumps({'success':success,'data':{'certificates':certs}}))
    def prep_live(self,**kw):certificate(self.private/'live',**kw)
    def prep_acme(self,rc):
        d=self.private/'prod-certs/example.com_ecc'; d.mkdir(parents=True,exist_ok=True)
        c=self.private/'fixture';certificate(c)
        for src,dst in [('key.pem','example.com.key'),('cert.pem','example.com.cer'),('ca.pem','ca.cer'),('fullchain.pem','fullchain.cer')]:shutil.copy(c/src,d/dst)
        self.write_exe(self.private/'engine/acme.sh',f'#!/bin/sh\necho "simulated ACME result"\nexit {rc}\n')
    def test_backend_requires_authentication_everywhere(self):
        for query in ('','api=status'):
            self.assertIn('401 Unauthorized',self.request(env={'TEST_USER':''},query=query))
        self.assertIn('403 Forbidden',self.request(env={'TEST_GROUPS':'users'}))
        self.assertIn('401 Unauthorized',self.request({'action':'apply'},env={'TEST_USER':''}))
    def require_dsm_session(self):
        # Model DSM's cookie + SynoToken contract instead of an unconditional
        # username response. Tokens alone never authenticate a request.
        self.write_exe(self.root/'usr/syno/synoman/webman/modules/authenticate.cgi','''#!/bin/sh
[ "${HTTP_COOKIE:-}" = 'id=offline-admin-session' ] || exit 0
case "&${QUERY_STRING:-}&" in *'&SynoToken=offline-dsm-token&'*) ;; *) exit 0;; esac
printf '%s' "${TEST_USER-admin}"
''')
        self.env['HTTP_COOKIE']='id=offline-admin-session'
    def test_dsm_cookie_token_and_administrator_checks(self):
        self.require_dsm_session()
        for query in ('','api=status','SynoToken=incorrect','api=status&SynoToken=incorrect'):
            self.assertIn('401 Unauthorized',self.request(query=query))
        query='SynoToken=offline-dsm-token'
        self.assertIn('401 Unauthorized',self.request(query=query,env={'HTTP_COOKIE':''}))
        self.assertIn('403 Forbidden',self.request(query=query,env={'TEST_GROUPS':'users'}))
        self.assertIn('Content-Type: text/html',self.request(query=query))
        csrf=next(self.etc.glob('ui_csrf.*')).read_text()
        self.assertIn('403 Forbidden',self.request(dict(action='refresh',csrf='bad'),query=query))
        self.assertIn('401 Unauthorized',self.request(dict(action='refresh',csrf=csrf),query='SynoToken=incorrect'))
        response=self.request(dict(action='refresh',csrf=csrf),query=query)
        self.assertTrue(json.loads(response.split('\n\n',1)[1])['ok'])
    def test_status_route_accepts_additional_dsm_token(self):
        self.require_dsm_session()
        for query in ('api=status&SynoToken=offline-dsm-token','SynoToken=offline-dsm-token&api=status','SynoToken=offline-dsm-token&%61pi=%73tatus'):
            with self.subTest(query=query):
                response=self.request(query=query)
                self.assertIn('Content-Type: application/json',response)
                self.assertIn('state',json.loads(response.split('\n\n',1)[1]))
    def test_authentication_cannot_consume_settings_post_body(self):
        self.write_exe(self.root/'usr/syno/synoman/webman/modules/authenticate.cgi','''#!/bin/sh
[ "$REQUEST_METHOD" = GET ] && [ "$CONTENT_LENGTH" = 0 ] || exit 1
cat >/dev/null
printf '%s' admin
''')
        response=self.request(dict(action='save',csrf=self.csrf(),email='admin@example.com',domains='example.com',key_type='ec-384',cert_desc='Settings body retained',cf_token=''))
        self.assertIn('Settings saved',response)
        self.assertEqual(json.loads((self.etc/'settings.json').read_text())['cert_desc'],'Settings body retained')
    def test_desktop_launcher_carries_dsm_session_token(self):
        # Execute the real launcher constructor with both DSM token providers,
        # then send its generated URL through the real CGI/authentication gate.
        self.require_dsm_session()
        script='''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const urls=[];
for(const mode of ['desktop','urlAppend']){
  const defs={};let config;
  const context={SYNO:{SDS:{Session:mode==='desktop'?{SynoToken:'offline-dsm-token'}:{}}},
    window:{addEventListener(){}},document:{},
    Ext:{ns(){},id(){return 'test-frame';},define(name,definition){defs[name]=definition;},
      apply(target,extra){return Object.assign(target,extra);},
      urlAppend(url){return mode==='urlAppend'?url+'?SynoToken=offline-dsm-token':url;}}};
  vm.runInNewContext(source,context);
  defs['SYNO.SDS.SadlerACME.MainWindow'].constructor.call({callParent(args){config=args[0];}},{});
  urls.push(config.items[0].autoEl.src);
}
process.stdout.write(JSON.stringify(urls));
'''
        p=subprocess.run(['node','-e',script,str(ROOT/'src/ui/SadlerACME.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        for url in json.loads(p.stdout):
            self.assertEqual(url.count('SynoToken='),1)
            response=self.request(query=urlsplit(url).query)
            self.assertIn('Content-Type: text/html',response)
            self.assertNotIn('401 Unauthorized',response)
    def test_dashboard_keeps_session_on_polls_and_actions(self):
        self.require_dsm_session()
        html=self.request(query='SynoToken=offline-dsm-token')
        script=re.search(r'<script>(.*?)</script>',html,re.S).group(1)
        csrf=next(self.etc.glob('ui_csrf.*')).read_text()
        p=subprocess.run(['node',str(ROOT/'tests/session-ui.js')],input=json.dumps(dict(
            script=script,csrf=csrf,
            status=dict(last_deploy='2026-09-22 12:00:00',last_verified='2026-09-26 12:00:00'),
            expectedText=dict(lastDeploy='2026-09-22 12:00:00',lastVerified='2026-09-26 12:00:00'))),capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        requests=json.loads(p.stdout)
        self.assertEqual(len(requests),6)
        self.assertEqual([r['body']['action'] for r in requests if r['body']],['refresh','check','scheduler-status','clear-log','scheduler-status'])
        for request in requests:
            self.assertEqual(request['credentials'],'same-origin')
            response=self.request(request['body'],query=urlsplit(request['url']).query)
            self.assertIn('Content-Type: application/json',response)
            data=json.loads(response.split('\n\n',1)[1])
            self.assertTrue(data['ok'] if request['body'] else 'state' in data)
    def test_csrf_and_removed_credential_endpoint(self):
        self.assertIn('403 Forbidden',self.request(dict(action='apply',csrf='invalid')))
        self.assertIn('400 Bad Request',self.request(dict(action='scheduler-install',csrf=self.csrf())))
    def test_rendered_javascript_and_clean_bootstrap(self):
        html=self.request(); self.assertNotIn(TOKEN,html)
        self.assertRegex(html,r'id="installSchedulerBtn"[^>]*type="button">')
        js=re.search(r'<script>(.*?)</script>',html,re.S).group(1)
        f=self.root/'rendered.js';f.write_text(js)
        p=subprocess.run(['node','--check',str(f)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        json.loads(self.request(query='api=status').split('\n\n',1)[1])
    def test_dashboard_separates_deployment_and_verification_history(self):
        response=self.request(query='api=status')
        data=json.loads(response.split('\n\n',1)[1])
        for field in ('last_issue','last_renewal','last_deploy','last_verified','last_staging','deployment_method'):
            self.assertEqual(data[field],'Not recorded',field)
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        (self.status/'last_verified').write_text('2026-09-26 12:00:00\n')
        data=json.loads(self.request(query='api=status').split('\n\n',1)[1])
        self.assertEqual(data['last_deploy'],'2026-09-22 12:00:00')
        self.assertEqual(data['last_verified'],'2026-09-26 12:00:00')
        html=self.request()
        self.assertRegex(html,r'id="lastDeploy"[^>]*>2026-09-22 12:00:00</div>')
        self.assertRegex(html,r'id="lastVerified"[^>]*>2026-09-26 12:00:00</div>')
    def test_dashboard_renewal_setting_controls_schedule_and_poll_text(self):
        epoch=str(int(time.time())+21600)
        (self.status/'systemd_queue_state').write_text('active\n')
        (self.status/'scheduler_status').write_text('Installed and enabled\n')
        cases=[
            # Poll an enabled schedule into a page initially rendered disabled.
            ('0',epoch,'Disabled','Disabled','1',epoch),
            # A later disabled setting must hide even a stale epoch in a poll.
            ('1','','Enabled — every 6 hours','Waiting for timer status','0',epoch),
            # Enabled without a recorded schedule is distinct from disabled.
            ('1',epoch,'Enabled — every 6 hours',None,'1','')]
        for auto,stored_epoch,label,next_label,poll_auto,poll_epoch in cases:
            with self.subTest(auto=auto,stored_epoch=stored_epoch,poll_auto=poll_auto):
                (self.etc/'settings.json').write_text(json.dumps(dict(CONFIG,auto_renew=auto)))
                (self.status/'next_auto_epoch').write_text(stored_epoch+'\n')
                (self.status/'systemd_timer_state').write_text('active\n')
                data=json.loads(self.request(query='api=status').split('\n\n',1)[1])
                self.assertEqual(data['auto_renew'],auto)
                self.assertEqual(data['next_auto'],stored_epoch if auto=='1' else '')
                html=self.request()
                self.assertRegex(html,r'id="autoRenew"[^>]*>'+re.escape(label)+r'</div>')
                next_node=re.search(r'<span id="nextAuto"([^>]*)>([^<]*)</span>',html)
                self.assertIsNotNone(next_node)
                self.assertIn('data-epoch="'+(stored_epoch if auto=='1' else '')+'"',next_node.group(1))
                self.assertIn('data-enabled="'+auto+'"',next_node.group(1))
                if next_label is not None:self.assertEqual(next_node.group(2),next_label)
                script=re.search(r'<script>(.*?)</script>',html,re.S).group(1)
                csrf=next(self.etc.glob('ui_csrf.*')).read_text()
                fixture=dict(script=script,csrf=csrf,
                    initialText=dict(autoRenew=label,nextAuto=next_node.group(2)),
                    attributes=dict(nextAuto={'data-enabled':auto,'data-epoch':stored_epoch if auto=='1' else '', 'data-timer':'active'}),
                    status=dict(auto_renew=poll_auto,auto_renew_text='Enabled — every 6 hours' if poll_auto=='1' else 'Disabled',next_auto=poll_epoch,timer_state='active'),
                    expectedText=dict(autoRenew='Enabled — every 6 hours' if poll_auto=='1' else 'Disabled'))
                if next_label is not None:fixture['expectedInitialNextText']=next_label
                else:fixture['expectedInitialNextEpoch']=stored_epoch
                if poll_auto=='0':fixture['expectedText']['nextAuto']='Disabled'
                elif not poll_epoch:fixture['expectedText']['nextAuto']='Waiting for timer status'
                else:fixture['expectedNextEpoch']=poll_epoch
                p=subprocess.run(['node',str(ROOT/'tests/session-ui.js')],input=json.dumps(fixture),capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stderr)
    def test_dashboard_hides_unavailable_or_invalid_timer_deadlines(self):
        (self.status/'systemd_queue_state').write_text('active\n')
        (self.status/'scheduler_status').write_text('Installed and enabled\n')
        future=str(int(time.time())+21600)
        for timer,epoch,expected in [('inactive',future,'Timer inactive'),('failed',future,'Timer failed'),('Unknown',future,'Waiting for timer status'),('active','n/a','Waiting for timer status'),('active','0','Waiting for timer status'),('active','999999999999999','Waiting for timer status')]:
            with self.subTest(timer=timer,epoch=epoch):
                (self.status/'systemd_timer_state').write_text(timer)
                (self.status/'next_auto_epoch').write_text(epoch)
                data=json.loads(self.request(query='api=status').split('\n\n',1)[1])
                self.assertEqual(data['next_auto'],'')
                html=self.request();self.assertIn('>'+expected+'</span>',html)
                script=re.search(r'<script>(.*?)</script>',html,re.S).group(1)
                fixture=dict(script=script,csrf=next(self.etc.glob('ui_csrf.*')).read_text(),
                    initialText=dict(autoRenew=data['auto_renew_text'],nextAuto=expected),
                    attributes=dict(nextAuto={'data-enabled':'1','data-epoch':'','data-timer':timer}),
                    status=dict(auto_renew='1',auto_renew_text=data['auto_renew_text'],next_auto=epoch,timer_state=timer),
                    expectedInitialNextText=expected,
                    expectedText=dict(autoRenew=data['auto_renew_text'],nextAuto=expected))
                p=subprocess.run(['node',str(ROOT/'tests/session-ui.js')],input=json.dumps(fixture),capture_output=True,text=True,timeout=15)
                self.assertEqual(p.returncode,0,p.stderr)
    def test_atomic_settings_encoding_and_blank_token(self):
        desc='A&B 100% "quoted" \\ café\rtext'
        response=self.request(dict(action='save',csrf=self.csrf(),email='a+b@example.com',domains='EXAMPLE.COM\n*.EXAMPLE.COM\nexample.com',key_type='ec-384',cert_desc=desc,cf_token='',auto_renew='1',dns_sleep='90'))
        self.assertIn('Settings saved',response)
        conf=json.loads((self.etc/'settings.json').read_text())
        self.assertEqual(conf['cert_desc'],desc);self.assertEqual(conf['cf_token'],TOKEN)
        self.assertEqual(conf['domains'],CONFIG['domains']);self.assertEqual(conf['dns_sleep'],'90')
        old=(self.etc/'settings.json').read_bytes()
        self.request(dict(action='save',csrf=self.csrf(),email='bad',domains='bad',key_type='bad'))
        self.assertEqual((self.etc/'settings.json').read_bytes(),old)
        self.assertEqual((self.etc/'settings.json').stat().st_mode&0o777,0o600)
    def test_legacy_settings_migration(self):
        (self.etc/'settings.json').unlink()
        for k,v in CONFIG.items():
            if k!='dns_sleep':(self.etc/k).write_text(('\n'.join(v) if isinstance(v,list) else v)+'\n')
        self.request();conf=json.loads((self.etc/'settings.json').read_text())
        self.assertEqual(conf['cf_token'],TOKEN);self.assertFalse((self.etc/'cf_token').exists())
    def test_queue_unique_snapshots_and_bound(self):
        first=self.job();conf=dict(CONFIG,cert_desc='second');(self.etc/'settings.json').write_text(json.dumps(conf))
        second=self.job();self.assertNotEqual(first,second)
        self.assertEqual(json.loads((self.inbox/first).read_text())['config']['cert_desc'],CONFIG['cert_desc'])
        for _ in range(3):self.job()
        self.assertIn('409 Conflict',self.request(dict(action='refresh',csrf=self.csrf())))
        self.assertEqual(len(list(self.inbox.glob('*.job'))),5)
    def test_full_worker_drains_jobs_already_queued(self):
        first=self.job();second=self.job()
        p=self.full_worker();self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(len(list(self.inbox.glob('*.job'))),0)
        for job_id in (first,second):
            receipt=json.loads((self.status/'jobs'/f'{job_id}.json').read_text())
            self.assertEqual((receipt['job_id'],receipt['result']),(job_id,'completed'))
        self.assertEqual((self.status/'last_job').read_text().strip(),second)
        self.assertEqual((self.status/'last_job_result').read_text().strip(),'completed')
        self.assertEqual(self.private.stat().st_mode&0o777,0o700)
        self.assertEqual(self.inbox.stat().st_mode&0o7777,0o1770)

    def test_full_worker_rescans_for_job_arriving_while_active(self):
        first=self.job()
        # Keep the first refresh inside DSM inventory long enough to submit a
        # second job while the worker service equivalent is still active.
        self.write_exe(self.root/'usr/syno/bin/synowebapi',
                       '#!/bin/sh\nsleep 1\ncat "'+str(self.listfile)+'"\n')
        p=subprocess.Popen(['sh',str(self.worker),'worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           text=True,env=self.env)
        deadline=time.time()+2
        while time.time()<deadline:
            active=self.private/'active-job'
            if active.exists() and active.read_text().strip()==first:break
            time.sleep(0.02)
        else:
            p.kill();self.fail('first job never became active')
        second=self.job()
        stdout,stderr=p.communicate(timeout=10)
        self.assertEqual(p.returncode,0,stderr+'\n'+stdout)
        self.assertFalse(list(self.inbox.glob('*.job')))
        for job_id in (first,second):
            receipt=json.loads((self.status/'jobs'/f'{job_id}.json').read_text())
            self.assertEqual((receipt['job_id'],receipt['result']),(job_id,'completed'))
        self.assertEqual((self.status/'last_job').read_text().strip(),second)

    def test_malformed_and_symlink_jobs_do_not_poison_queue(self):
        (self.inbox/'not-valid.job').write_text('{}')
        p=self.full_worker();self.assertNotEqual(p.returncode,0)
        self.assertFalse((self.inbox/'not-valid.job').exists())
        (self.inbox/'12-aabb.job').symlink_to(self.etc/'settings.json')
        p=self.full_worker();self.assertNotEqual(p.returncode,0)
        self.assertTrue((self.etc/'settings.json').exists());self.assertFalse((self.inbox/'12-aabb.job').exists())
    def test_stop_cancels_queued_job_without_path_loop(self):
        self.job();(self.var/'package.running').unlink()
        p=self.full_worker();self.assertNotEqual(p.returncode,0)
        self.assertFalse(list(self.inbox.glob('*.job')))
        self.assertIn('Package stopped',(self.status/'message').read_text())
    def test_stale_lock_file_is_not_a_lock(self):
        (self.private/'worker.lock').touch();self.job()
        self.assertEqual(self.full_worker().returncode,0)
    def test_keypair_and_certificate_validation(self):
        self.prep_live()
        self.shell('load_config\nvalidate_live_keypair\nvalidate_certificate "$LIVE"')
        (self.private/'live/key.pem').write_text('not a key');(self.private/'live/cert.pem').write_text('not a certificate')
        self.shell('validate_live_keypair',expected=1)
        self.prep_live(mismatch=True);self.shell('validate_live_keypair',expected=1)
        self.prep_live(expired=True);self.shell('load_config\nvalidate_certificate "$LIVE"',expected=1)
        self.prep_live(domains=['example.com']);self.shell('load_config\nvalidate_certificate "$LIVE"',expected=1)
    def test_acme_error_is_not_masked_by_old_files(self):
        self.prep_acme(1)
        self.shell('load_config\nissue_cert "$PROD_CFG" "$PROD_CERTS" "$LE_PROD" 0',expected=1)
        self.assertIn('ACME issuance failed',(self.status/'message').read_text())
    def test_acme_skip_requires_valid_matching_certificate(self):
        self.prep_acme(2)
        self.shell('load_config\nissue_cert "$PROD_CFG" "$PROD_CERTS" "$LE_PROD" 0')
        conf=dict(CONFIG,key_type='ec-256');(self.private/'work/config.json').write_text(json.dumps(conf))
        self.shell('load_config\nissue_cert "$PROD_CFG" "$PROD_CERTS" "$LE_PROD" 0',expected=1)
    def test_registration_error_not_masked_by_account_file(self):
        self.prep_acme(1);(self.private/'prod-config').mkdir();(self.private/'prod-config/account.conf').touch()
        self.shell('load_config\nregister_account "$PROD_CFG" "$PROD_CERTS" "$LE_PROD"',expected=1)
        self.assertIn('registration failed',(self.status/'message').read_text())
    def test_renewal_always_reconciles_deployment(self):
        self.prep_acme(2)
        self.shell('''load_config
config_signature > "$APPLIED_SIG"
ensure_engine() { :; }
adopt_legacy_profile() { :; }
register_account() { :; }
deploy_dsm() { touch "$ROOT_STATE/deploy-called"; }
run_check
''')
        self.assertTrue((self.private/'deploy-called').exists())
        self.assertTrue((self.private/'live').is_symlink())
    def test_expired_live_certificate_not_reused(self):
        self.prep_live(expired=True)
        p=self.shell('''load_config
config_signature > "$APPLIED_SIG"
ensure_engine() { :; }
adopt_legacy_profile() { :; }
register_account() { :; }
issue_cert() { echo issued > "$ROOT_STATE/issued"; exit 21; }
run_apply
''',expected=21)
        self.assertTrue((self.private/'issued').exists())
    def test_dsm_errors_clear_stale_health(self):
        for k,v in [('dsm_cert_id','old'),('dsm_match','yes'),('dsm_default','true')]: (self.status/k).write_text(v)
        self.set_list([],success=False)
        self.shell('CERT_DESC="SadlerACME wildcard"\nrefresh_dsm_metadata',expected=1)
        self.assertEqual((self.status/'dsm_match').read_text().strip(),'unknown')
        self.assertEqual((self.status/'dsm_cert_id').read_text().strip(),'')
    def test_verification_time_advances_only_for_positive_fingerprint_match(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        self.set_list([dict(id='abc',desc=CONFIG['cert_desc'],is_default=True)])
        shutil.copy(self.private/'live/cert.pem',archive/'cert.pem')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-26 12:00:00')
        self.assertEqual((self.status/'dsm_match').read_text().strip(),'yes')
        old=self.private/'old-certificate';certificate(old)
        shutil.copy(old/'cert.pem',archive/'cert.pem')
        for state in ('mismatch','missing-pem','missing-slot','api-error'):
            with self.subTest(state=state):
                if state=='missing-pem':(archive/'cert.pem').unlink()
                if state=='missing-slot':self.set_list([])
                if state=='api-error':self.set_list([],success=False)
                self.shell('load_config\nnow_iso() { echo "2026-09-27 12:00:00"; }\nrefresh_dsm_metadata',expected=1 if state=='api-error' else 0)
                self.assertNotEqual((self.status/'dsm_match').read_text().strip(),'yes')
                self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-26 12:00:00')
    def test_unchanged_deployment_preserves_actual_deployment_time(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        shutil.copy(self.private/'live/cert.pem',archive/'cert.pem')
        self.set_list([dict(id='abc',desc=CONFIG['cert_desc'],is_default=True)])
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        (self.status/'deployment_method').write_text('Local cert-store replacement\n')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\ndeploy_dsm')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-26 12:00:00')
        self.assertEqual((self.status/'deployment_method').read_text().strip(),'Local cert-store replacement')
    def test_replacement_records_deployment_only_after_successful_reload(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        old=self.private/'old-certificate';certificate(old)
        for src,dst in [('key.pem','privkey.pem'),('cert.pem','cert.pem'),('ca.pem','chain.pem'),('fullchain.pem','fullchain.pem')]:shutil.copy(old/src,archive/dst)
        self.set_list([dict(id='abc',desc=CONFIG['cert_desc'],is_default=False)])
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        (self.status/'last_verified').write_text('2026-09-22 12:01:00\n')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\ndeploy_dsm',expected=1,env={'TEST_W3_RC':'1'})
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-22 12:01:00')
        self.assertEqual((archive/'cert.pem').read_bytes(),(old/'cert.pem').read_bytes())
        self.shell('recover_transaction\nload_config\nnow_iso() { echo "2026-09-27 12:00:00"; }\ndeploy_dsm')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-27 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-27 12:00:00')
        self.assertEqual((archive/'cert.pem').read_bytes(),(self.private/'live/cert.pem').read_bytes())
    def assert_new_slot_import_uses_string_default(self, default_on_create, expected):
        self.prep_live()
        conf=dict(CONFIG,default_on_create=default_on_create)
        (self.private/'work/config.json').write_text(json.dumps(conf))
        archive=self.root/'usr/syno/etc/certificate/_archive/newslot'
        argslog=self.root/'import-args.txt'
        listed=json.dumps({'success':True,'data':{'certificates':[dict(id='newslot',desc=CONFIG['cert_desc'],is_default=expected=='true')]}})
        script="\n".join([
            '#!/bin/sh',
            'case "$*" in',
            '  *method=import*)',
            f"    printf '%s\\n' \"$*\" > \"{argslog}\"",
            f'    mkdir -p "{archive}"',
            f'    cp "{self.private}/live/cert.pem" "{archive}/cert.pem"',
            f"    printf '%s' '{listed}' > \"{self.listfile}\"",
            "    printf '%s' '{\"success\":true}'",
            '    ;;',
            f'  *) cat "{self.listfile}";;',
            'esac',
            ''
        ])
        self.write_exe(self.root/'usr/syno/bin/synowebapi',script)
        self.shell('load_config\ndeploy_dsm')
        args=argslog.read_text()
        self.assertIn('as_default="'+expected+'"',args)
        self.assertNotRegex(args, r'(?:^|\s)as_default=(?:true|false)(?:\s|$)')

    def test_new_slot_import_encodes_default_true_as_string(self):
        self.assert_new_slot_import_uses_string_default('1','true')

    def test_new_slot_import_encodes_default_false_as_string(self):
        self.assert_new_slot_import_uses_string_default('0','false')

    def test_confirmed_import_records_actual_deployment(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/newslot'
        listed=json.dumps({'success':True,'data':{'certificates':[dict(id='newslot',desc=CONFIG['cert_desc'],is_default=False)]}})
        self.write_exe(self.root/'usr/syno/bin/synowebapi',f'''#!/bin/sh
case "$*" in
  *method=import*)
    mkdir -p "{archive}"
    cp "{self.private}/live/cert.pem" "{archive}/cert.pem"
    printf '%s' '{listed}' > "{self.listfile}"
    printf '%s' '{{"success":true}}'
    ;;
  *) cat "{self.listfile}";;
esac
''')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\ndeploy_dsm')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-26 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-26 12:00:00')
        self.assertEqual((self.status/'deployment_method').read_text().strip(),'Local DSM WebAPI creation')
    def test_committed_replacement_history_waits_for_mailplus_recovery(self):
        self.prep_live();old=self.private/'old-certificate';certificate(old)
        archive=self.root/'usr/syno/etc/certificate/_archive/abc'
        mailplus=self.root/'usr/local/etc/certificate/MailPlus-Server/dovecot'
        for target in (archive,mailplus):
            target.mkdir(parents=True)
            for src,dst in [('key.pem','privkey.pem'),('cert.pem','cert.pem'),('ca.pem','chain.pem'),('fullchain.pem','fullchain.pem')]:shutil.copy(old/src,target/dst)
        self.set_list([dict(id='abc',desc=CONFIG['cert_desc'],is_default=False)])
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\ndeploy_dsm',expected=1,env={'TEST_RESTART_RC':'1'})
        self.assertEqual((archive/'cert.pem').read_bytes(),(self.private/'live/cert.pem').read_bytes())
        self.assertEqual((mailplus/'cert.pem').read_bytes(),(self.private/'live/cert.pem').read_bytes())
        self.assertFalse((self.private/'transaction.pending').exists())
        self.assertTrue((self.private/'reload.pending').exists())
        self.assertTrue((self.private/'deployment-history.pending').exists())
        self.shell('load_config\nnow_iso() { echo "2026-09-26 13:00:00"; }\nrefresh_dsm_metadata')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-26 13:00:00')
        self.shell('load_config\nfinish_pending_reload\nnow_iso() { echo "2026-09-27 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-27 12:00:00')
        self.assertFalse((self.private/'deployment-history.pending').exists())
        self.assertFalse((self.private/'reload.pending').exists())
        self.shell('load_config\nnow_iso() { echo "2026-09-28 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-27 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-28 12:00:00')
    def test_import_history_recovers_after_temporary_verification_failure(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/newslot';failure=self.root/'fail-list'
        listed=json.dumps({'success':True,'data':{'certificates':[dict(id='newslot',desc=CONFIG['cert_desc'],is_default=False)]}})
        self.write_exe(self.root/'usr/syno/bin/synowebapi',f'''#!/bin/sh
case "$*" in
  *method=import*)
    mkdir -p "{archive}"
    cp "{self.private}/live/cert.pem" "{archive}/cert.pem"
    printf '%s' '{listed}' > "{self.listfile}"
    touch "{failure}"
    printf '%s' '{{"success":true}}'
    ;;
  *) [ ! -f "{failure}" ] || exit 17; cat "{self.listfile}";;
esac
''')
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\ndeploy_dsm',expected=1)
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
        self.assertTrue((self.private/'deployment-history.pending').exists())
        failure.unlink()
        self.shell('load_config\nnow_iso() { echo "2026-09-27 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-27 12:00:00')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-27 12:00:00')
        self.assertFalse((self.private/'deployment-history.pending').exists())
        self.shell('load_config\nnow_iso() { echo "2026-09-28 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-27 12:00:00')
    def test_pending_history_requires_matching_fingerprint_and_durable_publication(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        shutil.copy(self.private/'live/cert.pem',archive/'cert.pem')
        self.set_list([dict(id='abc',desc=CONFIG['cert_desc'],is_default=False)])
        pending=self.private/'deployment-history.pending';pending.write_text('0'*64+'\n')
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        self.shell('load_config\nnow_iso() { echo "2026-09-26 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertTrue(pending.exists())
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
        self.assertEqual((self.status/'dsm_match').read_text().strip(),'yes')
        pending.write_text(self.shell('cert_fp_normalized "$LIVE/cert.pem"').stdout.strip()+'\n')
        self.write_exe(self.bin/'mv','''#!/bin/sh
for arg do last=$arg; done
case "$last" in */status/last_deploy) exit 17;; esac
exec /bin/mv "$@"
''')
        self.shell('load_config\nnow_iso() { echo "2026-09-27 12:00:00"; }\nrefresh_dsm_metadata',expected=1)
        self.assertTrue(pending.exists())
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
        (self.bin/'mv').unlink()
        self.shell('load_config\nnow_iso() { echo "2026-09-28 12:00:00"; }\nrefresh_dsm_metadata')
        self.assertFalse(pending.exists())
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-28 12:00:00')
    def test_old_ambiguous_deployment_history_is_migrated_once_at_worker_entry(self):
        old='2026-09-22 12:00:00'
        (self.status/'last_deploy').write_text(old+'\n')
        for name in ('last_issue','last_renewal','last_staging'):(self.status/name).write_text('recorded '+name+'\n')
        p=self.full_worker('systemd-bootstrap',{'TEST_SERVICE_STATE':'active'})
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue((self.private/'deployment-history-v2').exists())
        self.assertEqual((self.private/'legacy-last-deploy').read_text().strip(),old)
        self.assertEqual((self.private/'legacy-last-deploy').stat().st_mode&0o777,0o600)
        self.assertEqual((self.status/'last_verified').read_text().strip(),old)
        self.assertFalse((self.status/'last_deploy').exists() and (self.status/'last_deploy').read_text().strip())
        for name in ('last_issue','last_renewal','last_staging'):
            self.assertEqual((self.status/name).read_text().strip(),'recorded '+name)
        (self.status/'last_deploy').write_text('2026-09-26 12:00:00\n')
        p=self.full_worker('systemd-bootstrap',{'TEST_SERVICE_STATE':'active'})
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-26 12:00:00')
        self.assertEqual((self.private/'legacy-last-deploy').read_text().strip(),old)
    def test_history_migration_preserves_newer_verification_and_fresh_install_has_no_history(self):
        self.shell('migrate_deployment_history')
        self.assertTrue((self.private/'deployment-history-v2').exists())
        self.assertFalse((self.status/'last_verified').exists())
        self.assertFalse((self.private/'legacy-last-deploy').exists())
        (self.private/'deployment-history-v2').unlink()
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        (self.status/'last_verified').write_text('2026-09-26 12:00:00\n')
        self.shell('migrate_deployment_history')
        self.assertEqual((self.status/'last_verified').read_text().strip(),'2026-09-26 12:00:00')
    def test_duplicate_descriptions_and_stable_id(self):
        self.set_list([dict(id='one',desc=CONFIG['cert_desc'],is_default=False),dict(id='two',desc=CONFIG['cert_desc'],is_default=True)])
        self.shell('CERT_DESC="SadlerACME wildcard"\nlist_dsm_certificate',expected=2)
        (self.private/'dsm-id').write_text('two')
        self.shell('CERT_DESC="renamed"\nlist_dsm_certificate\n[ "$id" = two ] && [ "$is_default" = true ]')
    def test_import_success_without_fingerprint_confirmation_fails(self):
        self.prep_live()
        (self.status/'last_deploy').write_text('2026-09-22 12:00:00\n')
        self.shell('load_config\ndeploy_dsm',expected=1)
        self.assertIn('fingerprint does not match',(self.status/'message').read_text())
        self.assertEqual((self.status/'last_deploy').read_text().strip(),'2026-09-22 12:00:00')
    def test_backup_failure_never_restores_incomplete_data(self):
        self.prep_live();archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        for src,dst in [('key.pem','privkey.pem'),('cert.pem','cert.pem'),('ca.pem','chain.pem'),('fullchain.pem','fullchain.pem')]:shutil.copy(self.private/'live'/src,archive/dst)
        original={p.name:p.read_bytes() for p in archive.iterdir()}
        self.write_exe(self.bin/'cp','#!/bin/sh\ncase "$*" in *dsm-backups*cert.pem*) exit 17;; *) exec /bin/cp "$@";; esac\n')
        self.shell('load_config\nreplace_existing_slot_local abc',expected=1)
        self.assertEqual(original,{p.name:p.read_bytes() for p in archive.iterdir()})
        self.assertFalse((self.private/'transaction.pending').exists())
        self.assertIn('before any DSM files',(self.status/'message').read_text())
    def test_complete_backup_restores_present_and_absent_files(self):
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        (archive/'cert.pem').write_text('original');backup=self.private/'dsm-backups/txn.test';backup.mkdir(parents=True)
        self.shell(f'backup_dsm_target "{archive}" "{backup}" 1\nrestore_dsm_backups "{backup}"',expected=1)
        (backup/'targets').write_text(str(archive)+'\n');(backup/'complete').touch();(archive/'cert.pem').write_text('changed');(archive/'privkey.pem').write_text('new')
        (self.private/'transaction.pending').write_text(str(backup))
        (self.private/'deployment-history.pending').write_text('uncommitted-fingerprint\n')
        self.shell('recover_transaction')
        self.assertEqual((archive/'cert.pem').read_text(),'original');self.assertFalse((archive/'privkey.pem').exists())
        self.assertFalse((self.private/'transaction.pending').exists())
        self.assertFalse((self.private/'deployment-history.pending').exists())
    def test_reload_failure_keeps_retry_journal(self):
        (self.private/'reload.pending').write_text(str(self.root/'usr/local/etc/certificate/MailPlus-Server/dovecot')+'\n')
        self.shell('finish_pending_reload',expected=1,env={'TEST_RESTART_RC':'1'})
        self.assertTrue((self.private/'reload.pending').exists())
        self.shell('finish_pending_reload')
        self.assertFalse((self.private/'reload.pending').exists())
    def test_sql_failure_is_not_missing_task(self):
        self.shell('scheduler_status',env={'TEST_SQL_FAIL':'1'})
        self.assertEqual((self.status/'scheduler_status').read_text().strip(),'Unable to inspect')
    def test_scheduler_logs_changes_but_keeps_unchanged_checks_fresh(self):
        base=dict(TEST_SCHEDULER_ROW='1|bootup|0|/bin/systemctl start pkg-sadleracme-bootstrap.service|script')
        self.shell('scheduler_status',env=base)
        logpath=self.private/'sadleracme.log';first=logpath.read_text()
        self.assertIn('Scheduler status',first)
        (self.status/'scheduler_last_check').write_text('old\n')
        self.shell('now_iso() { echo "2026-09-26 12:00:00"; }\nscheduler_status',env=base)
        self.assertEqual(logpath.read_text(),first)
        self.assertEqual((self.status/'scheduler_last_check').read_text().strip(),'2026-09-26 12:00:00')
        self.write_exe(self.bin/'systemctl','''#!/bin/sh
case "$*" in
  *pkg-sadleracme-queue.path*) echo "${TEST_QUEUE_STATE:-inactive}";;
  *pkg-sadleracme-renew.timer*) echo "${TEST_TIMER_STATE:-inactive}";;
  *) exit 0;;
esac
''')
        changes=[dict(base,TEST_QUEUE_STATE='active'),dict(base,TEST_QUEUE_STATE='active',TEST_TIMER_STATE='active'),
                 dict(TEST_SCHEDULER_ROW='1|bootup|0|wrong command A|script'),
                 dict(TEST_SCHEDULER_ROW='1|bootup|0|wrong command B|script'),
                 dict(TEST_SCHEDULER_ROW='1|bootup|99|wrong command B|script'),
                 dict(TEST_SCHEDULER_ROW='1|shutdown|99|wrong command B|script')]
        previous=first
        for env in changes:
            with self.subTest(env=env):
                self.shell('scheduler_status',env=env)
                current=logpath.read_text()
                self.assertGreater(len(current),len(previous))
                self.shell('scheduler_status',env=env)
                self.assertEqual(logpath.read_text(),current)
                previous=current
    def test_successful_dsm_list_suppresses_benign_stderr(self):
        self.write_exe(self.root/'usr/syno/bin/synowebapi',f'#!/bin/sh\necho "routine WebAPI trace" >&2\ncat "{self.listfile}"\n')
        self.shell('load_config\nlist_dsm_certificate\npublish_log')
        for path in (self.private/'sadleracme.log',self.status/'log'):
            self.assertNotIn('routine WebAPI trace',path.read_text() if path.exists() else '')
    def test_failed_dsm_list_retains_diagnostics_and_redacts_credentials(self):
        for mode in ('command','api','schema'):
            with self.subTest(mode=mode):
                for path in (self.private/'sadleracme.log',self.status/'log'):
                    if path.exists():path.unlink()
                output={'command':'exit 17','api':'echo \'{"success":false}\'','schema':'echo \'{"success":true,"data":{"certificates":{}}}\''}[mode]
                self.write_exe(self.root/'usr/syno/bin/synowebapi',f'#!/bin/sh\necho "DSM diagnostic marker {TOKEN}" >&2\n{output}\n')
                self.shell('load_config\nlist_dsm_certificate',expected=1)
                raw=(self.private/'sadleracme.log').read_text()
                published=(self.status/'log').read_text()
                self.assertIn('DSM diagnostic marker',raw)
                self.assertIn('DSM diagnostic marker',published)
                self.assertRegex(published,r'(?i)(failed|invalid|error|rejected|malformed)')
                self.assertNotIn(TOKEN,published)
    def test_log_redacts_token_across_rotation_and_pem(self):
        self.shell('load_config\nprintf "%s\\n" "$CF_TOKEN" "-----BEGIN PRIVATE KEY-----" "secret" "-----END PRIVATE KEY-----" >> "$LOG"\nCF_TOKEN=new_token\npublish_log')
        published=(self.status/'log').read_text();self.assertNotIn(TOKEN,published);self.assertNotIn('secret',published)
    def test_lifecycle_busy_upgrade_and_uninstall_gates(self):
        for unit in ('worker','renew','bootstrap','setup','setup-expire','transfer-expire'):
            for state in ('active','activating','deactivating','reloading'):
                with self.subTest(unit=unit,state=state):
                    busy=self.lifecycle_hook('preupgrade',{'TEST_SERVICE_UNIT':f'pkg-sadleracme-{unit}.service','TEST_SERVICE_STATE':state})
                    self.assertEqual(busy.returncode,1);self.assertIn('SadlerACME is busy',busy.stderr)
        self.assertEqual(self.lifecycle_hook('preuninst',{'SYNOPKG_PKG_STATUS':'UPGRADE'}).returncode,0)
        self.assertEqual(self.lifecycle_hook('preuninst',{'SYNOPKG_PKG_STATUS':'UNINSTALL'}).returncode,1)
        (self.status/'uninstall_ready').write_text('yes')
        (self.status/'uninstall_ready').chmod(0o644)
        # A boolean alone cannot authorize removal without the independent
        # cleanup monitor, even if an earlier version left that boolean behind.
        self.assertEqual(self.lifecycle_hook('preuninst',{'SYNOPKG_PKG_STATUS':'UNINSTALL'}).returncode,1)
        removal=self.root/'usr/local/etc/sadleracme-removal';removal.mkdir()
        (removal/'armed').write_text('a'*64+'\n')
        self.shell('package_storage_capture "$VAR" var "'+str(removal/'package-var')+'"\npackage_storage_capture "$ETC" etc "'+str(removal/'package-etc')+'"')
        env={'SYNOPKG_PKG_STATUS':'UNINSTALL','TEST_SERVICE_UNIT':'sadleracme-cleanup.service','TEST_SERVICE_STATE':'active'}
        self.assertEqual(self.lifecycle_hook('preuninst',env).returncode,0)
        self.assertEqual(self.lifecycle_hook('preuninst',dict(env,TEST_SERVICE_STATE='inactive')).returncode,1)
    def test_lifecycle_unknown_state_rejects_upgrade_and_restores_stop_marker(self):
        marker=self.var/'package.running';original=b'original start timestamp\n\n'
        # Query failures are uncertain even when their output looks inactive.
        cases=[('worker',dict(TEST_SHOW_RC='1')),
               ('renew',dict(TEST_SHOW_REPORT='')),
               ('bootstrap',dict(TEST_SERVICE_STATE='unknown')),
               ('worker',dict(TEST_LOAD_STATE='error')),
               ('renew',dict(TEST_SHOW_REPORT='LoadState=loaded\n')),
               ('bootstrap',dict(TEST_SHOW_REPORT='inactive\n'))]
        self.write_exe(self.bin/'sleep',f'#!/bin/sh\necho unexpected > "{self.root}/slept"\n')
        for unit,report in cases:
            env=dict(report,TEST_SERVICE_UNIT=f'pkg-sadleracme-{unit}.service',SYNOPKG_TEMP_LOGFILE=str(self.root/'lifecycle-error'))
            with self.subTest(unit=unit,report=report):
                p=self.lifecycle_hook('preupgrade',env)
                self.assertEqual(p.returncode,1,p.stderr)
                self.assertTrue(p.stderr.strip())
                self.assertEqual((self.root/'lifecycle-error').read_text().strip(),p.stderr.strip())
                for initially_running in (True,False):
                    if initially_running:marker.write_bytes(original);marker.chmod(0o640)
                    elif marker.exists():marker.unlink()
                    p=self.lifecycle_hook('start-stop-status',env,args=('stop',))
                    self.assertEqual(p.returncode,1,p.stderr)
                    self.assertTrue(p.stderr.strip())
                    self.assertEqual(marker.exists(),initially_running)
                    if initially_running:
                        self.assertEqual(marker.read_bytes(),original)
                        self.assertEqual(marker.stat().st_mode&0o777,0o640)
                    self.assertFalse((self.root/'slept').exists(),'unknown state should fail promptly rather than wait')
    def test_lifecycle_known_idle_and_explicit_missing_units_are_allowed(self):
        cases=[dict(TEST_SERVICE_STATE='inactive'),dict(TEST_SERVICE_STATE='failed'),
               dict(TEST_LOAD_STATE='masked',TEST_SERVICE_STATE='inactive'),
               dict(TEST_LOAD_STATE='masked',TEST_SERVICE_STATE='failed'),
               dict(TEST_LOAD_STATE='not-found',TEST_SERVICE_STATE='inactive',TEST_SHOW_RC='0'),
               dict(TEST_LOAD_STATE='not-found',TEST_SERVICE_STATE='inactive',TEST_SHOW_RC='1')]
        marker=self.var/'package.running'
        for env in cases:
            with self.subTest(env=env):
                p=self.lifecycle_hook('preupgrade',env)
                self.assertEqual(p.returncode,0,p.stderr)
                marker.write_text('running\n')
                p=self.lifecycle_hook('start-stop-status',env,args=('stop',))
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertFalse(marker.exists())
                self.assertEqual(self.lifecycle_hook('start-stop-status',args=('status',)).returncode,3)
    def test_stop_waits_for_busy_operation_without_stopping_services(self):
        marker=self.var/'package.running';state=self.root/'service-state';state.write_text('active')
        count=self.root/'sleep-count';calls=self.root/'systemctl-calls';seen=self.root/'marker-seen-while-waiting'
        self.write_exe(self.bin/'sleep',f'''#!/bin/sh
[ ! -e "{marker}" ] || touch "{seen}"
n=0; [ ! -f "{count}" ] || n=$(cat "{count}")
n=$((n + 1)); printf '%s' "$n" > "{count}"
[ "$n" -lt 3 ] || printf inactive > "{state}"
''')
        p=self.lifecycle_hook('start-stop-status',dict(TEST_SERVICE_UNIT='pkg-sadleracme-renew.service',
            TEST_SERVICE_STATE_FILE=str(state),TEST_SYSTEMCTL_LOG=str(calls)),args=('stop',))
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(count.read_text(),'3')
        self.assertFalse(marker.exists());self.assertFalse(seen.exists())
        self.assertTrue(all(line.startswith('show ') for line in calls.read_text().splitlines()))
    def test_stop_timeout_restores_exact_marker_or_preserves_initial_absence(self):
        marker=self.var/'package.running';count=self.root/'sleep-count';original=b'original start timestamp\n\n'
        self.write_exe(self.bin/'sleep',f'''#!/bin/sh
n=0; [ ! -f "{count}" ] || n=$(cat "{count}")
printf '%s' "$((n + 1))" > "{count}"
''')
        for initially_running in (True,False):
            with self.subTest(initially_running=initially_running):
                if initially_running:marker.write_bytes(original);marker.chmod(0o640)
                elif marker.exists():marker.unlink()
                if count.exists():count.unlink()
                # This deliberately executes all 90 wait iterations. Sleep is
                # mocked, but hundreds of child processes can exceed 15s in
                # a constrained execution environment. Keep other hooks at 15s.
                p=self.lifecycle_hook('start-stop-status',dict(TEST_SERVICE_UNIT='pkg-sadleracme-bootstrap.service',TEST_SERVICE_STATE='active'),args=('stop',),timeout=60)
                self.assertEqual(p.returncode,1,p.stderr)
                self.assertEqual(count.read_text(),'90')
                self.assertIn('completing a certificate operation',p.stderr)
                self.assertEqual(marker.exists(),initially_running)
                if initially_running:
                    self.assertEqual(marker.read_bytes(),original)
                    self.assertEqual(marker.stat().st_mode&0o777,0o640)
    def test_interrupted_stop_restores_exact_marker_or_preserves_initial_absence(self):
        marker=self.var/'package.running';original=b'original start timestamp\n\n'
        self.write_exe(self.bin/'sleep','#!/bin/sh\nkill -TERM "$PPID"\n')
        for initially_running in (True,False):
            with self.subTest(initially_running=initially_running):
                if initially_running:marker.write_bytes(original);marker.chmod(0o640)
                elif marker.exists():marker.unlink()
                p=self.lifecycle_hook('start-stop-status',dict(TEST_SERVICE_STATE='active'),args=('stop',))
                self.assertEqual(p.returncode,1,p.stderr)
                self.assertEqual(marker.exists(),initially_running)
                if initially_running:
                    self.assertEqual(marker.read_bytes(),original)
                    self.assertEqual(marker.stat().st_mode&0o777,0o640)
                self.assertFalse(list(self.var.glob('package.running.stop.*')))
    def test_install_upgrade_defer_privileged_prerequisites(self):
        # Model the package account's lack of execute access. No host DSM file
        # is changed; executable checks use the temporary DSM fixtures.
        for state in ('inaccessible','missing'):
            for tool in ('synowebapi','synow3tool'):
                path=self.root/'usr/syno/bin'/tool
                if state=='inaccessible':path.chmod(0o600)
                else:path.unlink()
            for hook in ('preinst','preupgrade'):
                with self.subTest(state=state,hook=hook):
                    p=self.lifecycle_hook(hook)
                    self.assertEqual(p.returncode,0,p.stderr)
    def test_install_upgrade_still_require_authentication_helper(self):
        auth=self.root/'usr/syno/synoman/webman/modules/authenticate.cgi'
        for state in ('inaccessible','missing'):
            if state=='inaccessible':auth.chmod(0o600)
            else:auth.unlink()
            for hook in ('preinst','preupgrade'):
                with self.subTest(state=state,hook=hook):
                    logfile=self.root/'install-error.log'
                    p=self.lifecycle_hook(hook,{'SYNOPKG_TEMP_LOGFILE':str(logfile)})
                    self.assertEqual(p.returncode,1)
                    self.assertIn(str(auth),p.stderr)
                    self.assertIn(str(auth),logfile.read_text())
    def test_bootstrap_checks_privileged_tools_before_migration(self):
        for tool in ('synowebapi','synow3tool'):
            path=self.root/'usr/syno/bin'/tool;original=path.read_text()
            for state in ('inaccessible','missing'):
                with self.subTest(tool=tool,state=state):
                    if state=='inaccessible':path.chmod(0o600)
                    else:path.unlink()
                    try:
                        p=self.full_worker('systemd-bootstrap',{'TEST_SERVICE_STATE':'active'})
                        self.assertEqual(p.returncode,1,p.stderr)
                        self.assertIn('unavailable to root: '+str(path),(self.status/'message').read_text())
                        self.assertEqual((self.status/'last_action').read_text().strip(),'preflight')
                        self.assertFalse((self.private/'migration-v1').exists())
                        self.assertFalse((self.status/'systemd_bootstrap_last').exists())
                        self.assertFalse(list(self.private.glob('work.*')))
                    finally:self.write_exe(path,original)
    def test_pinned_engine_rejects_tampering(self):
        share=self.base/'target/share/acme.sh-3.1.5';shutil.copytree(ROOT/'vendor/acme.sh-3.1.5',share)
        self.shell('ensure_engine')
        (self.private/'engine/acme.sh').write_text('tampered');(share/'acme.sh').write_text('tampered')
        self.shell('ensure_engine',expected=1)
        self.assertIn('integrity check failed',(self.status/'message').read_text())
    def test_legacy_live_import_never_sources_old_shell_configuration(self):
        legacy=self.var/'root/live';certificate(legacy)
        (self.var/'root/prod-config').mkdir();(self.var/'root/prod-config/account.conf').write_text(f'touch "{self.root}/EXECUTED"\n')
        self.shell('migrate_legacy_live\nload_config\nadopt_legacy_profile')
        self.assertFalse((self.root/'EXECUTED').exists())
        self.assertTrue((self.private/'live').is_symlink())
        self.assertTrue((self.private/'prod-certs/example.com_ecc/example.com.conf').exists())

    def test_successful_replacement_and_reload_failure_rollback(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        old=self.private/'old-certificate';certificate(old)
        for src,dst in [('key.pem','privkey.pem'),('cert.pem','cert.pem'),('ca.pem','chain.pem'),('fullchain.pem','fullchain.pem')]:shutil.copy(old/src,archive/dst)
        original={p.name:p.read_bytes() for p in archive.iterdir()}
        # Force DSM regeneration to fail. The transaction must remain marked
        # until DSM can reload the restored files successfully.
        self.shell('load_config\nreplace_existing_slot_local abc',expected=1,env={'TEST_W3_RC':'1'})
        self.assertEqual(original,{p.name:p.read_bytes() for p in archive.iterdir()})
        self.assertTrue((self.private/'transaction.pending').exists())
        self.shell('recover_transaction\nload_config\nreplace_existing_slot_local abc')
        self.assertEqual((archive/'cert.pem').read_bytes(),(self.private/'live/cert.pem').read_bytes())
        self.assertFalse((self.private/'transaction.pending').exists())
    def test_package_writable_or_symlink_certificate_target_rejected(self):
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        archive.chmod(0o777)
        self.shell(f'safe_certificate_target "{archive}"',expected=1)
        archive.chmod(0o755)
        link=archive.parent/'alias';link.symlink_to(archive)
        self.shell(f'safe_certificate_target "{link}"',expected=1)
    def test_real_acme_engine_accepts_migrated_skip_profile(self):
        # Use the actual pinned engine offline: future NextRenewTime must skip
        # before any ACME HTTP request. A curl mock fails closed if attempted.
        self.prep_live();self.shell('load_config\nadopt_legacy_profile')
        share=self.base/'target/share/acme.sh-3.1.5';shutil.copytree(ROOT/'vendor/acme.sh-3.1.5',share)
        self.write_exe(self.bin/'curl','#!/bin/sh\necho NETWORK_BLOCKED >&2\nexit 97\n')
        self.shell('load_config\nensure_engine\nissue_cert "$PROD_CFG" "$PROD_CERTS" "$LE_PROD" 0')
        self.assertNotIn('NETWORK_BLOCKED',(self.private/'sadleracme.log').read_text())
    def test_unchanged_live_generation_is_reused(self):
        self.prep_live();shutil.copytree(self.private/'live',self.private/'work/candidate')
        self.shell('load_config\ninstall_live_files')
        self.assertFalse(list(self.private.glob('live-gen.*')))
    def test_clean_bootstrap_and_prepared_uninstall(self):
        self.prep_live()
        archive=self.root/'usr/syno/etc/certificate/_archive/abc';archive.mkdir(parents=True)
        shutil.copy(self.private/'live/cert.pem',archive/'cert.pem')
        self.set_list([dict(id='abc',desc=CONFIG['cert_desc'],is_default=True)])
        account=self.private/'prod-config/account.conf';account.parent.mkdir();account.write_text('retained-account-data\n')
        backup=self.private/'dsm-backups/retained-cert.pem';backup.parent.mkdir();shutil.copy(self.private/'live/cert.pem',backup)
        retained=[self.etc/'settings.json',account,backup,archive/'cert.pem',*list((self.private/'live').iterdir())]
        original={p:p.read_bytes() for p in retained}
        p=self.full_worker('systemd-bootstrap',{'TEST_SERVICE_STATE':'active'})
        self.assertEqual(p.returncode,0,p.stderr)
        (self.root/'usr/local/lib/systemd/system').mkdir(parents=True)
        self.job('prepare-uninstall');self.job('force')
        p=self.full_worker(env={'TEST_SERVICE_UNIT':'sadleracme-cleanup.service','TEST_SERVICE_STATE':'active'})
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'yes')
        self.assertFalse(list(self.inbox.glob('*.job')))
        self.assertEqual(self.inbox.stat().st_mode&0o7777,0o700)
        self.assertTrue((self.private/'uninstall-ready').exists())
        self.assertEqual(self.lifecycle_hook('postuninst').returncode,0)
        obsolete=self.var/'queue/request';obsolete.parent.mkdir();obsolete.write_text('old request\n')
        self.assertEqual(self.lifecycle_hook('postinst').returncode,0)
        self.assertFalse(obsolete.exists())
        # Resuming a prepared install must stop its running cleanup monitor.
        # Track that transition rather than reporting every unit permanently
        # active through TEST_SERVICE_STATE, including after a successful stop.
        cleanup_state=self.root/'cleanup-state';cleanup_state.write_text('active\n')
        systemctl_base=self.bin/'systemctl-base';(self.bin/'systemctl').rename(systemctl_base)
        self.write_exe(self.bin/'systemctl', f'''#!/bin/sh
if [ "$1" = stop ] && [ "${{2:-}}" = sadleracme-cleanup.service ]; then
  printf 'inactive\\n' > '{cleanup_state}'
fi
if [ "${{2:-}}" = sadleracme-cleanup.service ]; then
  TEST_SERVICE_STATE_FILE='{cleanup_state}'; export TEST_SERVICE_STATE_FILE
fi
exec '{systemctl_base}' "$@"
''')
        p=self.full_worker('systemd-bootstrap',{'TEST_SERVICE_STATE':'active'})
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(cleanup_state.read_text().strip(),'inactive')
        self.assertFalse((self.private/'uninstall-ready').exists())
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
        self.assertEqual(self.inbox.stat().st_mode&0o7777,0o1770)
        self.assertEqual(original,{p:p.read_bytes() for p in retained})
        self.job('refresh')
        p=self.full_worker();self.assertEqual(p.returncode,0,p.stderr)
        self.assertFalse(list(self.inbox.glob('*.job')))
        self.assertEqual(original,{p:p.read_bytes() for p in retained})
    def test_generated_launcher_executes_verified_copy_and_rejects_tamper(self):
        build=self.root/'unit-build';payload=build/'payload/bin/sadleracme-root';payload.parent.mkdir(parents=True)
        marker=self.root/'verified-executed'
        payload.write_text(f'#!/bin/sh\necho yes > "{marker}"\n')
        units=build/'spk/conf/systemd';units.mkdir(parents=True)
        (units/'worker.service').write_text('[Service]\nExecStart=@VERIFIED_WORKER@ worker\n')
        subprocess.run(['python3',str(ROOT/'tools/build_units.py'),str(build)],check=True)
        line=next(x for x in (units/'worker.service').read_text().splitlines() if x.startswith('ExecStart='))
        command=json.loads(line.removeprefix('ExecStart=/bin/sh -c ')).replace('$$','$')
        command=command.replace('/var/packages/sadleracme/target/bin/sadleracme-root',str(payload)).replace('/run/sadleracme.',str(self.root/'snapshot.'))
        run=subprocess.run(['sh','-c',command],text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertTrue(marker.exists())
        self.assertFalse(list(self.root.glob('snapshot.*')))
        marker.unlink();payload.write_text('#!/bin/sh\necho tampered\n')
        run=subprocess.run(['sh','-c',command],text=True,capture_output=True)
        self.assertNotEqual(run.returncode,0);self.assertFalse(marker.exists())
        self.assertFalse(list(self.root.glob('snapshot.*')))

    def test_kernel_lock_serializes_worker_entry(self):
        job=self.job()
        with (self.private/'worker.lock').open('w') as held:
            fcntl.flock(held,fcntl.LOCK_EX)
            p=subprocess.Popen(['sh',str(self.worker),'worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=self.env)
            try:
                time.sleep(0.15)
                self.assertIsNone(p.poll());self.assertTrue((self.inbox/job).exists())
                fcntl.flock(held,fcntl.LOCK_UN)
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,0,err)
            finally:
                if p.poll() is None:p.kill();p.wait()
        self.assertFalse((self.inbox/job).exists())

    def test_production_rejects_untrusted_chain_but_staging_is_separate(self):
        self.prep_live();TEST_CA_BUNDLE.write_text('')
        self.shell('load_config\nvalidate_certificate "$LIVE"',expected=1)
        self.shell('load_config\nvalidate_certificate "$LIVE" staging')

    def test_acme_headers_and_saved_tokens_are_not_external_arguments(self):
        argsfile=self.root/'curl-args';headers=self.root/'curl-headers';sedargs=self.root/'sed-args'
        self.write_exe(self.bin/'curl', f'''#!/bin/sh
printf '%s\\n' "$@" > "{argsfile}"
while [ "$#" -gt 0 ]; do
  if [ "$1" = --config ]; then shift; cat "$1" > "{headers}"; fi
  shift
done
''')
        self.write_exe(self.bin/'sed', f'''#!/bin/sh
printf '%s\\n' "$@" >> "{sedargs}"
exec /bin/sed "$@"
''')
        self.write_exe(self.private/'engine/acme.sh', '''#!/bin/sh
curl --silent -H "Authorization: Bearer $CF_Token" -H 'Content-Type: application/json' --data '{"test":true}' https://fixture.invalid
printf 'SAVED_CF_Token=old\\n' | sed "s|^SAVED_CF_Token=.*$|SAVED_CF_Token=$CF_Token|" > "$WORK/saved"
''')
        self.shell('load_config\nCF_Token="$CF_TOKEN" acme_invoke')
        self.assertNotIn(TOKEN,argsfile.read_text());self.assertNotIn(TOKEN,sedargs.read_text())
        self.assertIn(TOKEN,headers.read_text());self.assertIn(TOKEN,(self.private/'work/saved').read_text())
        self.assertIn('https://fixture.invalid',argsfile.read_text())
        self.assertFalse(list((self.private/'work').glob('curl.*')))
        self.assertFalse(list((self.private/'work').glob('sed.*')))

if __name__=='__main__':unittest.main(verbosity=2)
