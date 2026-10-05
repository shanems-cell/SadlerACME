#!/usr/bin/env python3
"""Isolated lifecycle fixtures. No real systemd/DSM scheduler or package removal.
Rewrites every DSM path into a temporary root. Verifies safe gates and ordering,
not DSM service registration or Package Center's on-device hook permissions.
"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from assemble_worker import render_emergency
BOOT = 'SadlerACME Bootstrap|1|bootup|0|/bin/systemctl start pkg-sadleracme-bootstrap.service|script'
SETUP = 'SadlerACME Setup|0|bootup|0|/bin/systemctl start pkg-sadleracme-setup.service|script'

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sadler-lifecycle-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root/'var/packages/sadleracme'
        self.appdata = self.root/'volume1/@appdata/sadleracme'
        self.appconf = self.root/'volume1/@appconf/sadleracme'
        self.base.mkdir(parents=True)
        self.appdata.mkdir(parents=True); self.appconf.mkdir(parents=True)
        (self.base/'var').symlink_to(self.appdata)
        (self.base/'etc').symlink_to(self.appconf)
        self.protected = self.root/'usr/local/etc/sadleracme'
        self.private = self.protected/'private'
        self.work = self.private/'work'
        self.status = self.protected/'status'
        self.removal = self.root/'usr/local/etc/sadleracme-removal'
        self.units = self.root/'usr/local/lib/systemd/system'
        self.bin = self.root/'bin'
        self.state = self.root/'systemd.json'
        self.enabled = self.root/'enabled.json'
        self.calls = self.root/'calls'
        for path in (self.base/'etc',self.base/'var',self.base/'scripts', self.work,self.status,self.protected/'inbox', self.units,self.bin, self.root/'usr/syno/etc/esynoscheduler', self.root/'usr/syno/bin'):
            path.mkdir(parents=True,exist_ok=True)
        (self.base/'var/package.running').touch()
        (self.root/'usr/syno/etc/esynoscheduler/esynoscheduler.db').touch()
        self.state.write_text('{}')
        self.enabled.write_text('{}')
        self.env = dict(os.environ, PATH=str(self.bin)+':/usr/bin:/bin', TEST_STATE=str(self.state),TEST_ENABLED=str(self.enabled),TEST_CALLS=str(self.calls), TEST_BASE=str(self.base))
        self.exe(self.bin/'systemctl', '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['TEST_STATE']); d=json.loads(p.read_text()); a=sys.argv[1:]
with open(os.environ['TEST_CALLS'],'a') as f:f.write(' '.join(a)+'\\n')
if '--now' in a:
 print("systemctl: unrecognized option '--now'",file=sys.stderr);sys.exit(1)
if os.environ.get('TEST_FAIL') and os.environ['TEST_FAIL'] in ' '.join(a):sys.exit(1)
cmd=a[0]
if cmd=='show':
 u=a[1]; state=d.get(u,'inactive')
 if '--value' in a:print(state)
 else:
  if 'LoadState' in a:print('LoadState=loaded')
  if 'ActiveState' in a:print('ActiveState='+state)
elif cmd=='is-active': print(d.get(a[-1],'inactive'));sys.exit(0 if d.get(a[-1])=='active' else 3)
elif cmd in ('start','restart','stop'):
 if os.environ.get('TEST_NOOP') and os.environ['TEST_NOOP'] in ' '.join(a):sys.exit(0)
 for u in a[1:]:
  if not u.startswith('-'):d[u]='active' if cmd in ('start','restart') else 'inactive'
 p.write_text(json.dumps(d))
elif cmd in ('enable','disable'):
 p=Path(os.environ['TEST_ENABLED']); d=json.loads(p.read_text())
 for u in a[1:]:
  if not u.startswith('-'):d[u]=cmd=='enable'
 p.write_text(json.dumps(d))
''')
        self.exe(self.bin/'sqlite3', '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
if os.environ.get('TEST_SQL_ARGS'):
 with open(os.environ['TEST_SQL_ARGS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
if os.environ.get('TEST_SQL_STDERR'):print(os.environ['TEST_SQL_STDERR'],file=sys.stderr)
if os.environ.get('TEST_SQL_PARTIAL'):print(os.environ['TEST_SQL_PARTIAL'])
if os.environ.get('TEST_SQL_FAIL','0') != '0':sys.exit(int(os.environ['TEST_SQL_FAIL']))
print(Path(os.environ['TEST_TASKS_FILE']).read_text() if os.environ.get('TEST_TASKS_FILE') else os.environ.get('TEST_TASKS',''),end='')
''')
        self.exe(self.bin/'sleep', '#!/bin/sh\nexit 33\n')
        self.exe(self.root/'usr/syno/bin/synowebapi', '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
with open(os.environ['TEST_CALLS'],'a') as f:f.write('synowebapi '+' '.join(sys.argv[1:])+'\\n')
if os.environ.get('TEST_DELETE_FAIL'):print('{"success":false}');sys.exit(0)
if not os.environ.get('TEST_DELETE_STALE'):
 p=Path(os.environ['TEST_TASKS_FILE']); name=json.loads(next(x.split('=',1)[1] for x in sys.argv if x.startswith('task_name=')))
 p.write_text('\\n'.join(x for x in p.read_text().splitlines() if x.split('|')[0]!=name))
print('{"success":true}')
''')
        self.exe(self.root/'usr/syno/bin/synopkg', '''#!/usr/bin/python3
import os,shutil,sys
if os.environ.get('TEST_PKG_FAIL'):sys.exit(1)
if sys.argv[1:] == ['uninstall','sadleracme']:shutil.rmtree(os.environ['TEST_BASE'])
''')
        prelude = '''#!/bin/sh
set -eu
umask 077
PKG=sadleracme
BASE=/var/packages/sadleracme
ETC=$BASE/etc
VAR=$BASE/var
PROTECTED=/usr/local/etc/sadleracme
ROOT_STATE=$PROTECTED/private
WORK=$ROOT_STATE/work
STATUS_DIR=$PROTECTED/status
INBOX=$PROTECTED/inbox
OPENSSL=$(command -v openssl)
SCHED_BOOT_COMMAND='/bin/systemctl start pkg-sadleracme-bootstrap.service'
write_public() { printf '%s\\n' "$2" > "$STATUS_DIR/$1"; chmod 0644 "$STATUS_DIR/$1"; }
write_status() { write_public state "$1"; write_public message "$2"; }
log() { printf '%s\\n' "$*" >> "$ROOT_STATE/test-log"; }
fail() { printf '%s\\n' "$1" >&2; exit 1; }
secure_directory() { [ ! -L "$1" ] || exit 1; mkdir -p "$1"; chmod "$2" "$1"; }
require_privileged_tools() { :; }
scheduler_status() { :; }
systemd_unit_state() { systemctl show "$1" -p ActiveState --value; }
'''
        self.functions = self.root/'functions.sh'
        helpers=(ROOT/'src/lib/package-storage.sh').read_text()
        lifecycle=(ROOT/'src/lib/lifecycle.sh').read_text().replace('# @PACKAGE_STORAGE_HELPERS@', helpers)
        self.functions.write_text(self.rewrite(prelude+helpers+lifecycle))
        for hook in ('preinst','preuninst','postuninst','start-stop-status'):
            self.exe(self.base/'scripts'/hook, self.rewrite((ROOT/'pkg/scripts'/hook).read_text()))
        self.emergency=self.root/'emergency.sh'
        self.exe(self.emergency,self.rewrite(render_emergency(ROOT)))
    def exe(self,path,text):
        path.write_text(text);path.chmod(0o755)
    def rewrite(self,text):
        text=re.sub(r'/var/packages|/usr/local|/usr/syno|/volume',lambda m:str(self.root)+m.group(),text)
        text=re.sub(r'^PATH=.*$',f'PATH={self.bin}:/usr/bin:/bin',text,flags=re.M)
        text=text.replace('while [ "$ps_parent" != / ]; do', 'while [ "$ps_parent" != "'+str(self.root)+'" ]; do')
        text=text.replace('while [ "$fs_parent" != / ]; do', 'while [ "$fs_parent" != "'+str(self.root)+'" ]; do')
        return text
    def sh(self,code,expected=0,env=None):
        p=subprocess.run(['sh','-c',f'. "{self.functions}"\n'+code],text=True,capture_output=True,env=dict(self.env,**(env or {})),timeout=10)
        self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
        return p
    def hook(self,name,expected=0,env=None):
        p=subprocess.run(['sh',str(self.base/'scripts'/name)],text=True,capture_output=True,env=dict(self.env,**(env or {})),timeout=10)
        self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
        return p
    def emergency_run(self,*args,expected=0,env=None):
        p=subprocess.run(['sh',str(self.emergency),*args],text=True,capture_output=True,env=dict(self.env,**(env or {})),timeout=10)
        self.assertEqual(p.returncode,expected,p.stdout+p.stderr)
        return p
    def task_env(self,rows):return {'TEST_TASKS':rows}
    def prepared(self):
        (self.private/'certificate-data').write_text('keep until confirmed')
        self.sh('prepare_uninstall')
    def test_fresh_install_allowed_but_task_intent_blocks(self):
        shutil.rmtree(self.protected)
        self.hook('preuninst')
        (self.base/'var/automation.requested').touch()
        self.hook('preuninst',1)
    def test_missing_readiness_blocks_initialized_install(self):self.hook('preuninst',1)
    def test_prepare_rejects_tasks_and_does_not_delete_data(self):
        (self.private/'certificate-data').write_text('keep')
        self.sh('prepare_uninstall',1,self.task_env(BOOT))
        self.assertEqual((self.private/'certificate-data').read_text(),'keep')
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
    def test_prepare_rejects_unknown_scheduler(self):self.sh('prepare_uninstall',1,{'TEST_SQL_FAIL':'1'})
    def test_scheduler_read_keeps_readonly_and_fixed_wait(self):
        args_file=self.root/'sqlite-args'
        p=self.sh('lifecycle_task_rows',env=dict(self.task_env(BOOT),TEST_SQL_ARGS=str(args_file)))
        self.assertEqual(p.stdout,BOOT)
        args=json.loads(args_file.read_text())
        self.assertEqual(args[:5],['-readonly','-cmd','.timeout 5000','-separator','|'])
        self.assertEqual(args[5],str(self.root/'usr/syno/etc/esynoscheduler/esynoscheduler.db'))
        self.assertEqual(args[6],"SELECT task_name,enable,event,owner,operation,operation_type FROM task WHERE task_name IN ('SadlerACME Bootstrap','SadlerACME Setup') OR operation LIKE '%pkg-sadleracme-%' OR operation LIKE '%sadleracme-root%';")
        self.assertEqual((self.work/'scheduler-read.diagnostic').read_text(),'')
    def test_scheduler_failure_categories_never_publish_raw_stderr_or_partial_rows(self):
        secret='fixture-secret-must-remain-private'
        cases=[('Error: database is locked',5,'busy/locked'),
               ('Error: database table is locked',6,'busy/locked'),
               ('Error: no such column: operation_type',1,'schema'),
               ('Error: unable to open database file',14,'access/open'),
               ('Error: something unexpected',23,'unknown')]
        for diagnostic,code,category in cases:
            with self.subTest(category=category,code=code):
                p=self.sh('finish_setup',1,{'TEST_SQL_FAIL':str(code),'TEST_SQL_STDERR':diagnostic+' '+secret,'TEST_SQL_PARTIAL':BOOT})
                self.assertIn(f'{category} (exit {code})',p.stderr)
                self.assertNotIn(secret,p.stderr+p.stdout)
                self.assertNotIn(BOOT,p.stderr+p.stdout)
                self.assertFalse(self.calls.exists(),'Failed inventory must not change services')
                self.assertEqual((self.status/'state').read_text().strip(),'running')
                self.assertIn(secret,(self.work/'scheduler-read.stderr').read_text())
                self.assertNotIn(secret,(self.work/'scheduler-read.diagnostic').read_text())
    def test_scheduler_missing_tool_and_database_are_distinct(self):
        self.sh('PATH=/nonexistent\nlifecycle_task_rows',127)
        self.assertEqual((self.work/'scheduler-read.diagnostic').read_text().strip(),'tool missing (exit 127)')
        (self.root/'usr/syno/etc/esynoscheduler/esynoscheduler.db').unlink()
        self.sh('lifecycle_task_rows',1)
        self.assertEqual((self.work/'scheduler-read.diagnostic').read_text().strip(),'access/open (exit 1)')
    def test_scheduler_success_clears_previous_failure_diagnostic(self):
        self.sh('lifecycle_task_rows',5,{'TEST_SQL_FAIL':'5','TEST_SQL_STDERR':'database is locked'})
        self.sh('lifecycle_task_rows',env=self.task_env(BOOT))
        self.assertEqual((self.work/'scheduler-read.diagnostic').read_text(),'')
        self.assertEqual((self.work/'scheduler-read.stderr').read_text(),'')
    def test_finish_still_refuses_wrong_tasks_and_logs_success(self):
        for rows in (BOOT+'\n'+BOOT,BOOT.replace('bootup','shutdown'),BOOT+'\n'+SETUP):
            self.sh('finish_setup',1,self.task_env(rows))
            self.assertFalse(self.calls.exists())
            self.assertFalse((self.private/'test-log').exists())
        self.sh('finish_setup',env=self.task_env(BOOT))
        self.assertEqual((self.status/'state').read_text().strip(),'success')
        self.assertIn('Permanent automation verified; queue watcher and renewal timer are active',(self.private/'test-log').read_text())
    def test_root_scheduler_status_uses_same_wait_and_private_diagnostic(self):
        worker=(ROOT/'src/bin/sadleracme-root').read_text()
        function='scheduler_status() {'+worker.split('scheduler_status() {',1)[1].split('\nsystemd_bootstrap() {',1)[0]
        code='''read_status_value() { cat "$STATUS_DIR/$1" 2>/dev/null || true; }
now_iso() { printf 'fixture-time\\n'; }
'''+ '\nRUN_MARKER="$VAR/package.running"\n' +(ROOT/'src/lib/timer-status.sh').read_text()+self.rewrite(function)+'\nscheduler_status'
        args_file=self.root/'sqlite-args'
        p=self.sh(code,env={'TEST_SQL_FAIL':'5','TEST_SQL_STDERR':'database is locked fixture-secret-private','TEST_SQL_ARGS':str(args_file)})
        self.assertEqual((self.status/'scheduler_status').read_text().strip(),'Unable to inspect')
        self.assertIn('busy/locked (exit 5)',(self.status/'scheduler_detail').read_text())
        self.assertEqual(json.loads(args_file.read_text())[:5],['-readonly','-cmd','.timeout 5000','-separator','|'])
        self.assertNotIn('fixture-secret-private',p.stdout+p.stderr+''.join(x.read_text() for x in self.status.iterdir()))
    def test_prepare_rejects_failed_service_stop(self):
        self.sh('prepare_uninstall',1,{'TEST_FAIL':'stop pkg-sadleracme-queue.path'})
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
    def test_prepare_rejects_failed_monitor_enable_or_restart(self):
        (self.private/'certificate-data').write_text('keep')
        for command in ('enable','restart'):
            with self.subTest(command=command):
                self.calls.write_text('')
                self.sh('prepare_uninstall',1,{'TEST_FAIL':command+' sadleracme-cleanup.service'})
                self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
                self.assertFalse((self.private/'uninstall-ready').exists())
                self.assertEqual((self.private/'certificate-data').read_text(),'keep')
                self.hook('preuninst',1)
                if command=='enable':
                    self.assertNotIn('restart sadleracme-cleanup.service',self.calls.read_text())
    def test_prepare_rejects_failed_transfer_timer_disable_or_stop(self):
        (self.private/'certificate-data').write_text('keep')
        timer='pkg-sadleracme-transfer-expire.timer'
        for command in ('disable','stop'):
            with self.subTest(command=command):
                self.state.write_text(json.dumps({timer:'active'}))
                self.enabled.write_text(json.dumps({timer:True}))
                self.calls.write_text('')
                self.sh('prepare_uninstall',1,{'TEST_FAIL':command+' '+timer})
                self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
                self.assertFalse((self.private/'uninstall-ready').exists())
                self.assertEqual((self.private/'certificate-data').read_text(),'keep')
                self.assertEqual(json.loads(self.state.read_text())[timer],'active')
                self.assertEqual(json.loads(self.enabled.read_text())[timer],command=='disable')
                self.assertFalse(self.removal.exists(),'Do not arm removal after a failed expiry timer stop')
                if command=='disable':self.assertNotIn('stop '+timer,self.calls.read_text())
                self.hook('preuninst',1)
    def test_prepare_requires_monitor_active_after_restart(self):
        (self.private/'certificate-data').write_text('keep')
        self.sh('prepare_uninstall',1,{'TEST_NOOP':'restart sadleracme-cleanup.service'})
        self.assertTrue(json.loads(self.enabled.read_text())['sadleracme-cleanup.service'])
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
        self.assertFalse((self.private/'uninstall-ready').exists())
        self.assertEqual((self.private/'certificate-data').read_text(),'keep')
        self.hook('preuninst',1)
    def test_prepare_arms_monitor_preserves_data_and_allows_uninstall(self):
        self.prepared()
        self.assertTrue((self.private/'certificate-data').exists())
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'yes')
        calls=self.calls.read_text().splitlines()
        self.assertLess(calls.index('disable pkg-sadleracme-transfer-expire.timer'),calls.index('stop pkg-sadleracme-transfer-expire.timer'))
        self.assertLess(calls.index('enable sadleracme-cleanup.service'),calls.index('restart sadleracme-cleanup.service'))
        self.assertTrue(json.loads(self.enabled.read_text())['sadleracme-cleanup.service'])
        self.hook('preuninst')
        d=json.loads(self.state.read_text());d['sadleracme-cleanup.service']='inactive';self.state.write_text(json.dumps(d))
        self.hook('preuninst',1)
    def test_postuninst_commit_does_not_erase_until_package_gone(self):
        self.prepared();self.hook('postuninst')
        p=subprocess.run(['sh',str(self.removal/'monitor')],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,33,p.stderr)
        self.assertTrue((self.private/'certificate-data').exists())
        certificate=self.root/'usr/syno/etc/certificate/_archive/kept/cert.pem'
        certificate.parent.mkdir(parents=True);certificate.write_text('DSM certificate remains')
        shutil.rmtree(self.base)
        p=subprocess.run(['sh',str(self.removal/'monitor')],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertFalse(self.protected.exists());self.assertFalse(self.removal.exists())
        self.assertEqual(certificate.read_text(),'DSM certificate remains')
    def test_monitor_requires_matching_commit_and_ready(self):
        self.prepared();self.hook('postuninst');shutil.rmtree(self.base)
        (self.removal/'signal/commit').write_text('0'*64+'\n')
        p=subprocess.run(['sh',str(self.removal/'monitor')],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,33,p.stderr);self.assertTrue(self.protected.exists())
        (self.removal/'signal/commit').write_text((self.removal/'armed').read_text())
        (self.status/'uninstall_ready').write_text('no\n')
        p=subprocess.run(['sh',str(self.removal/'monitor')],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,1,p.stderr);self.assertTrue(self.protected.exists())
    def test_monitor_releases_lock_if_package_reappears(self):
        self.prepared();self.hook('postuninst');shutil.rmtree(self.base)
        flock_log=self.root/'flock-log'
        self.exe(self.bin/'flock', f'''#!/bin/sh
printf '%s\\n' "$*" >> "{flock_log}"
/usr/bin/flock "$@" || exit 1
case "$1" in -w) mkdir -p "{self.base}";; esac
''')
        p=subprocess.run(['sh',str(self.removal/'monitor')],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,33,p.stderr)
        self.assertIn('-u 8',flock_log.read_text())
        self.assertTrue(self.protected.exists())
    def test_monitor_refuses_nested_mount(self):
        self.prepared();self.hook('postuninst');shutil.rmtree(self.base)
        self.exe(self.bin/'awk', f'''#!/bin/sh
case "$*" in */proc/self/mountinfo*) echo "{self.protected}/nested-volume";; *) exec /usr/bin/awk "$@";; esac
''')
        p=subprocess.run(['sh',str(self.removal/'monitor')],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertTrue(self.protected.exists())
    def test_upgrade_does_not_signal_removal(self):
        self.prepared();self.hook('postuninst',env={'SYNOPKG_PKG_STATUS':'UPGRADE'})
        self.assertFalse((self.removal/'signal/commit').exists())
    def test_bootstrap_resume_invalidates_removal(self):
        self.prepared();self.sh('lifecycle_resume')
        self.assertFalse(self.removal.exists());self.assertFalse((self.private/'uninstall-ready').exists())
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
        self.assertFalse(json.loads(self.enabled.read_text())['sadleracme-cleanup.service'])
        self.assertEqual(json.loads(self.state.read_text())['sadleracme-cleanup.service'],'inactive')
        calls=self.calls.read_text().splitlines()
        self.assertLess(calls.index('disable sadleracme-cleanup.service'),calls.index('stop sadleracme-cleanup.service'))
    def test_failed_disarm_invalidates_ready_without_resuming_or_erasing_data(self):
        for command in ('disable','stop'):
            with self.subTest(command=command):
                self.prepared();self.calls.write_text('')
                self.sh('lifecycle_resume',1,{'TEST_FAIL':command+' sadleracme-cleanup.service'})
                self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
                self.assertFalse((self.private/'uninstall-ready').exists())
                self.assertEqual((self.private/'certificate-data').read_text(),'keep until confirmed')
                self.assertTrue(self.removal.exists())
                self.assertTrue((self.units/'sadleracme-cleanup.service').exists())
                self.assertEqual(json.loads(self.state.read_text())['sadleracme-cleanup.service'],'active')
                self.assertEqual(json.loads(self.enabled.read_text())['sadleracme-cleanup.service'],command=='disable')
                self.assertNotIn('start pkg-sadleracme-queue.path',self.calls.read_text())
                if command=='disable':self.assertNotIn('stop sadleracme-cleanup.service',self.calls.read_text())
                self.hook('preuninst',1)
    def test_disarm_requires_monitor_stopped_before_removing_files(self):
        self.prepared()
        self.sh('lifecycle_resume',1,{'TEST_NOOP':'stop sadleracme-cleanup.service'})
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
        self.assertTrue(self.removal.exists())
        self.assertTrue((self.units/'sadleracme-cleanup.service').exists())
        self.assertEqual((self.private/'certificate-data').read_text(),'keep until confirmed')
        self.hook('preuninst',1)
    def test_temporary_setup_starts_queue_not_renewal(self):
        self.sh('systemd_setup',env=self.task_env(SETUP))
        d=json.loads(self.state.read_text())
        self.assertEqual(d['pkg-sadleracme-queue.path'],'active')
        self.assertEqual(d['pkg-sadleracme-renew.timer'],'inactive')
        self.assertEqual((self.status/'setup_temporary').read_text().strip(),'yes')
        self.assertIn('restart pkg-sadleracme-setup-expire.timer',self.calls.read_text())
    def test_existing_permanent_setup_is_reused(self):
        self.sh('systemd_setup',env=self.task_env(BOOT))
        self.assertFalse((self.private/'setup-temporary').exists())
        self.assertNotIn('stop pkg-sadleracme-renew.timer',self.calls.read_text())
    def test_duplicate_tasks_rejected_before_service_mutation(self):
        self.sh('systemd_setup',1,self.task_env(BOOT+'\n'+BOOT))
        self.assertFalse(self.calls.exists())
    def test_cancel_preserves_newly_permanent_automation(self):
        self.sh('systemd_setup',env=self.task_env(SETUP))
        self.calls.write_text('')
        self.sh('cancel_setup',env=self.task_env(BOOT))
        self.assertNotIn('stop pkg-sadleracme-queue.path',self.calls.read_text())
        self.assertFalse((self.private/'setup-temporary').exists())
    def test_cancel_and_expiry_stop_only_temporary_resources(self):
        self.sh('systemd_setup',env=self.task_env(SETUP))
        (self.private/'setup-temporary').write_text('1\n')
        self.sh('setup_expired',env=self.task_env(SETUP))
        self.assertEqual((self.status/'setup_temporary').read_text().strip(),'no')
        self.assertIn('Remove the disabled SadlerACME Setup task',(self.status/'message').read_text())
        self.assertNotIn('stop pkg-sadleracme-transfer-expire.timer',self.calls.read_text())
    def test_stale_expiry_service_preserves_renewed_lease(self):
        self.sh('systemd_setup',env=self.task_env(SETUP))
        deadline=(self.private/'setup-temporary').read_text()
        self.calls.write_text('')
        self.sh('setup_expired',env=self.task_env(SETUP))
        self.assertEqual((self.private/'setup-temporary').read_text(),deadline)
        self.assertEqual(self.calls.read_text(),'')
    def test_invalid_lease_is_reported_without_stopping_existing_services(self):
        (self.private/'setup-temporary').write_text('invalid')
        self.sh('setup_expired',1)
        self.assertFalse(self.calls.exists())
    def test_finish_requires_permanent_and_no_temporary_task(self):
        self.sh('systemd_setup',env=self.task_env(SETUP))
        self.sh('finish_setup',1,self.task_env(BOOT+'\n'+SETUP))
        self.sh('finish_setup',env=self.task_env(BOOT))
        self.assertFalse((self.private/'setup-temporary').exists())
    def test_reprepare_failure_invalidates_old_ready(self):
        self.prepared()
        d=json.loads(self.state.read_text());d['pkg-sadleracme-queue.path']='active';self.state.write_text(json.dumps(d))
        self.sh('prepare_uninstall',1,{'TEST_FAIL':'stop pkg-sadleracme-queue.path'})
        self.assertEqual((self.status/'uninstall_ready').read_text().strip(),'no')
        self.hook('preuninst',1)
    def test_reprepare_restarts_monitor_for_new_nonce(self):
        self.prepared();first=(self.removal/'armed').read_text();self.calls.write_text('')
        self.sh('prepare_uninstall')
        self.assertNotEqual((self.removal/'armed').read_text(),first)
        self.assertIn('restart sadleracme-cleanup.service',self.calls.read_text())
        self.hook('postuninst')
        self.assertEqual((self.removal/'signal/commit').read_text(),(self.removal/'armed').read_text())
    def test_setup_after_abandoned_preparation_reopens_inbox(self):
        self.prepared();self.sh('systemd_setup',env=self.task_env(BOOT))
        self.assertEqual((self.protected/'inbox').stat().st_mode&0o7777,0o1770)
    def test_preinst_blocks_rapid_reinstall_until_cleanup_complete(self):
        self.prepared()
        p=self.hook('preinst',1)
        self.assertIn('Previous SadlerACME removal cleanup',p.stderr)
    def test_preparation_removes_temporary_exports_before_expiry_stop(self):
        transfers=self.protected/'transfers';transfers.mkdir();(transfers/'test.json').write_text('privatekey')
        (self.private/'live').mkdir();(self.private/'live/key.pem').write_text('keep')
        self.sh('prepare_uninstall',1,{'TEST_FAIL':'stop pkg-sadleracme-queue.path'})
        self.assertFalse((transfers/'test.json').exists())
        self.assertTrue((self.private/'live/key.pem').exists())
    def test_emergency_remove_tasks_validates_and_verifies_api(self):
        tasks=self.root/'tasks';tasks.write_text('SadlerACME Bootstrap|0|/bin/systemctl start pkg-sadleracme-bootstrap.service|script\nSadlerACME Setup|0|/bin/systemctl start pkg-sadleracme-setup.service|script\n')
        self.emergency_run('--remove','--remove-tasks','--confirm','REMOVE SADLERACME DATA',env={'TEST_TASKS_FILE':str(tasks)})
        self.assertEqual(tasks.read_text(),'')
        self.assertIn('api=SYNO.Core.EventScheduler method=delete',self.calls.read_text())
        self.assertFalse(self.base.exists())
    def test_emergency_remove_tasks_refuses_ambiguous_or_changed_command(self):
        good='SadlerACME Bootstrap|0|/bin/systemctl start pkg-sadleracme-bootstrap.service|script'
        for rows in (good+'\n'+good,good.replace('bootstrap.service','worker.service')):
            tasks=self.root/'tasks';tasks.write_text(rows)
            self.emergency_run('--remove','--remove-tasks','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_TASKS_FILE':str(tasks)})
            self.assertEqual(tasks.read_text(),rows)
            self.assertTrue(self.base.exists())
            self.assertFalse(self.calls.exists())
    def test_emergency_remove_tasks_rejects_api_failure_or_false_success(self):
        for failure in ('TEST_DELETE_FAIL','TEST_DELETE_STALE'):
            tasks=self.root/'tasks';tasks.write_text('SadlerACME Setup|0|/bin/systemctl start pkg-sadleracme-setup.service|script')
            self.emergency_run('--remove','--remove-tasks','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_TASKS_FILE':str(tasks),failure:'1'})
            self.assertTrue(self.base.exists());self.assertTrue(self.protected.exists())
    def test_emergency_check_read_only_and_requires_confirmation(self):
        self.emergency_run('--check')
        self.assertTrue(self.base.exists());self.assertTrue(self.protected.exists())
        self.emergency_run('--remove',expected=2)
        self.assertTrue(self.base.exists())
    def test_emergency_refuses_live_tasks(self):
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_TASKS':'SadlerACME Setup'})
        self.assertTrue(self.protected.exists())
    def test_emergency_failed_package_removal_restores_hooks_and_data(self):
        original=(self.base/'scripts/preuninst').read_text()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_PKG_FAIL':'1'})
        self.assertEqual((self.base/'scripts/preuninst').read_text(),original)
        self.assertTrue(self.protected.exists())
    def test_emergency_removes_only_app_after_package_manager(self):
        certificate=self.root/'usr/syno/etc/certificate/kept.pem';certificate.parent.mkdir(parents=True);certificate.write_text('kept')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(self.base.exists());self.assertFalse(self.protected.exists())
        self.assertEqual(certificate.read_text(),'kept')
    def test_emergency_removes_exact_residual_units_only(self):
        owned=self.units/'pkg-sadleracme-worker.service';owned.write_text('leftover')
        unrelated=self.units/'some-other-package.service';unrelated.write_text('keep')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(owned.exists());self.assertEqual(unrelated.read_text(),'keep')
    def test_emergency_retains_and_reports_unexpected_unit_symlink(self):
        unrelated=self.units/'some-other-package.service';unrelated.write_text('keep')
        alias=self.units/'pkg-sadleracme-worker.service';alias.symlink_to(unrelated)
        p=self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertTrue(alias.is_symlink());self.assertEqual(unrelated.read_text(),'keep')
        self.assertIn('unexpected unit paths',p.stderr)
    def test_emergency_pending_transaction_requires_specific_override(self):
        (self.private/'transaction.pending').write_text('recovery')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertTrue(self.private.exists())

if __name__=='__main__':unittest.main(verbosity=2)
