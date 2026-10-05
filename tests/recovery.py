#!/usr/bin/env python3
"""Offline recovery checks using the established synthetic DSM fixture.

No live NAS, DNS, ACME request, certificate issuance or DSM mutation is used.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest

spec = importlib.util.spec_from_file_location('sadler_regression', Path(__file__).with_name('regression.py'))
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)


class Recovery(regression.Regression):
    def setUp(self):
        super().setUp()
        # Read the assembled worker when available. During isolated extension
        # development append precisely the same verified-source extension.
        text = self.functions.read_text()
        if '\nbackup_export() {' not in text:
            text += '\n' + self.rewrite((regression.ROOT / 'src/lib/recovery.sh').read_text())
        self.functions.write_text(text)
        self.account = self.private / 'prod-config/ca/acme-v02.api.letsencrypt.org/directory/account.key'
        self.syslog = self.root / 'systemctl.log'
        self.env['TEST_SYSTEMCTL_LOG'] = str(self.syslog)
        self.transfer_state = self.root / 'transfer-timer-state.json'
        self.env['TEST_TRANSFER_TIMER_STATE'] = str(self.transfer_state)
        (self.bin / 'systemctl').rename(self.bin / 'systemctl-base')
        self.env['TEST_BASE_SYSTEMCTL'] = str(self.bin / 'systemctl-base')
        # Simulate the relevant systemd 219 limitation and independently track
        # boot enablement and runtime activation for the transfer-expiry timer.
        # Other units retain the established shared fixture behaviour.
        self.write_exe(self.bin / 'systemctl', f'#!{sys.executable}\n' + '''
import json, os, pathlib, sys
args = sys.argv[1:]
if '--now' in args:
    print('systemctl compatibility simulation: unsupported --now', file=sys.stderr)
    sys.exit(2)
if len(args) < 2 or args[1] != 'pkg-sadleracme-transfer-expire.timer':
    os.execv(os.environ['TEST_BASE_SYSTEMCTL'], [os.environ['TEST_BASE_SYSTEMCTL']] + args)
with open(os.environ['TEST_SYSTEMCTL_LOG'], 'a') as log:
    log.write(' '.join(args) + '\\n')
path = pathlib.Path(os.environ['TEST_TRANSFER_TIMER_STATE'])
state = json.loads(path.read_text()) if path.exists() else dict(enabled=False, active=False)
command = args[0]
if command == os.environ.get('TEST_TRANSFER_TIMER_FAIL'):
    sys.exit(1)
if command == 'enable': state['enabled'] = True
elif command == 'disable': state['enabled'] = False
elif command == 'start': state['active'] = not bool(os.environ.get('TEST_TRANSFER_TIMER_INACTIVE_AFTER_START'))
elif command == 'stop': state['active'] = False
elif command == 'show':
    active = 'active' if state['active'] else 'inactive'
    print(active if '--value' in args else 'LoadState=loaded\\nActiveState=' + active)
elif command == 'is-active':
    print('active' if state['active'] else 'inactive')
    sys.exit(0 if state['active'] else 3)
else:
    print('Unexpected transfer timer command in fixture', file=sys.stderr)
    sys.exit(90)
path.write_text(json.dumps(state))
''')
        # Any API beyond read-only certificate list is forbidden in this suite.
        self.write_exe(self.root / 'usr/syno/bin/synowebapi', f'''#!/bin/sh
printf '%s\\n' "$*" >> '{self.root / "dsm-calls"}'
case "$*" in *api=SYNO.Core.Certificate.CRT*method=list*) cat '{self.listfile}';; *) exit 91;; esac
''')
        self.write_exe(self.root / 'usr/syno/bin/synow3tool', '#!/bin/sh\nexit 92\n')
        self.commit = '''
commit_settings_from_file() {
  cp "$1" "$ETC/settings-test.new" && chmod 0600 "$ETC/settings-test.new" && mv -f "$ETC/settings-test.new" "$ETC/settings.json"
}
'''

    def export(self, cert=True):
        if cert:
            self.prep_live()
            self.account.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.private / 'live/key.pem', self.account)
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export')
        path = self.protected / 'transfers/abc123-456.json'
        return json.loads(path.read_text()), path

    def restore(self, backup, token=None, extra='', expected=0):
        config = dict(regression.CONFIG)
        config['cf_token'] = token if token is not None else 'fresh_cloudflare_token_01234567890123456789'
        (self.private / 'work/job.json').write_text(json.dumps(dict(action='restore', backup=backup, config=config)))
        return self.shell(self.commit + extra + '\nrestore_backup', expected=expected)

    def snapshot(self):
        # Exclude worker/status/transfers; compare only managed certificate state
        # and settings so a rejected upload cannot silently change either.
        out = {'settings': (self.etc / 'settings.json').read_bytes()}
        for name in ('live', 'prod-config', 'prod-certs', 'applied_signature', 'dsm-id', 'migration-v1'):
            path = self.private / name
            if path.is_file():
                out[name] = path.read_bytes()
            elif path.is_dir():
                for child in path.rglob('*'):
                    if child.is_file():
                        out[name + '/' + str(child.relative_to(path))] = child.read_bytes()
        return out

    def simulate_jq_without_rawfile(self, fail_stage=''):
        # This is a compatibility/failure simulation using the host jq, not a
        # claim that the suite ran on native jq 1.5. Only file paths and fixed
        # filters may reach argv; the log lets the test check that boundary.
        self.env['TEST_RECOVERY_REAL_JQ'] = shutil.which('jq')
        self.env['TEST_RECOVERY_JQ_FAIL_STAGE'] = fail_stage
        self.env['TEST_RECOVERY_JQ_ARGV'] = str(self.root / 'jq-argv.jsonl')
        self.write_exe(self.bin / 'jq', f'#!{sys.executable}\n' + '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['TEST_RECOVERY_JQ_ARGV'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if '--rawfile' in args:
    print('jq compatibility simulation: unsupported --rawfile', file=sys.stderr)
    sys.exit(2)
stage = os.environ['TEST_RECOVERY_JQ_FAIL_STAGE']
raw_input = args[-1] if '-Rs' in args else ''
fail = ((stage.startswith('pem:') and raw_input.endswith('/pem/' + stage[4:] + '.pem')) or
        (stage == 'account' and raw_input.endswith('/export/account.key')) or
        (stage == 'combine' and '--slurpfile' in args and 'fullchain' in args) or
        (stage == 'document' and '--slurpfile' in args and 'metadata' in args))
if stage and fail:
    print('jq export encoding failure simulation', file=sys.stderr)
    sys.exit(2)
os.execv(os.environ['TEST_RECOVERY_REAL_JQ'], [os.environ['TEST_RECOVERY_REAL_JQ']] + args)
''')

    def test_export_restore_without_rawfile_compatibility_simulation(self):
        self.simulate_jq_without_rawfile()
        doc, _ = self.export()
        for name in ('key', 'cert', 'ca', 'fullchain'):
            encoded = self.private / f'work/export/{name}.json'
            canonical = self.private / f'work/export/pem/{name}.pem'
            self.assertEqual(json.loads(encoded.read_text()), canonical.read_text())
            self.assertEqual(doc['certificate'][name + '.pem'], canonical.read_text())
            self.assertEqual(encoded.stat().st_mode & 0o777, 0o600)
        self.restore(doc)
        self.assertEqual((self.private / 'live/cert.pem').read_text(), doc['certificate']['cert.pem'])
        arguments = (self.root / 'jq-argv.jsonl').read_text()
        self.assertNotIn('--rawfile', arguments)
        self.assertNotIn('-----BEGIN', arguments)
        self.assertNotIn(regression.TOKEN, arguments)
        self.assertNotIn('PRIVATE KEY', ''.join(p.read_text() for p in self.status.iterdir() if p.is_file()))

    def test_export_encoding_failures_publish_nothing_and_preserve_managed_state(self):
        self.prep_live()
        self.account.parent.mkdir(parents=True)
        shutil.copy(self.private / 'live/key.pem', self.account)
        before = self.snapshot()
        cases = [(f'pem:{name}', 'Cannot encode certificate files for recovery backup')
                 for name in ('key', 'cert', 'ca', 'fullchain')]
        cases += [('combine', 'Cannot combine certificate files for recovery backup'),
                  ('account', 'Cannot encode ACME account key for recovery backup'),
                  ('document', 'Cannot encode recovery backup')]
        for stage, message in cases:
            with self.subTest(stage=stage):
                self.simulate_jq_without_rawfile(fail_stage=stage)
                self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export', expected=1)
                self.assertEqual((self.status / 'message').read_text().strip(), message)
                self.assertEqual((self.status / 'last_action').read_text().strip(), 'backup')
                self.assertFalse((self.protected / 'transfers/abc123-456.json').exists())
                self.assertFalse((self.status / 'backup_download').exists())
                self.assertNotIn('enable pkg-sadleracme-transfer-expire.timer', self.syslog.read_text())
                self.assertEqual(self.snapshot(), before)

    def test_export_encoding_failure_keeps_specific_error_through_exit_cleanup(self):
        self.prep_live()
        self.simulate_jq_without_rawfile(fail_stage='pem:key')
        before = self.snapshot()
        self.shell("ACTIVE_JOB=abc123-456.job\ntrap 'on_exit $?' EXIT\nbackup_export", expected=1)
        self.assertEqual((self.status / 'message').read_text().strip(),
                         'Cannot encode certificate files for recovery backup')
        self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'failed')
        self.assertFalse((self.private / 'work').exists())
        self.assertFalse((self.protected / 'transfers/abc123-456.json').exists())
        self.assertEqual(self.snapshot(), before)

    def test_export_stops_if_invalid_previous_transfer_cannot_be_removed(self):
        transfers = self.protected / 'transfers'
        transfers.mkdir()
        (transfers / 'abc123-000.json').symlink_to('missing.json')
        self.write_exe(self.bin / 'rm', '''#!/bin/sh
case "$*" in *abc123-000.json*) exit 9;; esac
exec /bin/rm "$@"
''')
        before = self.snapshot()
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export', expected=1)
        self.assertEqual((self.status / 'message').read_text().strip(),
                         'Cannot expire previous recovery downloads')
        self.assertFalse((transfers / 'abc123-456.json').exists())
        self.assertEqual(self.snapshot(), before)

    def test_export_stops_if_expired_download_status_cannot_be_cleared(self):
        (self.protected / 'transfers').mkdir()
        (self.status / 'backup_download').write_text('abc123-000\n')
        self.write_exe(self.bin / 'chmod', '''#!/bin/sh
case "$*" in *backup_download.tmp*) exit 9;; esac
exec /bin/chmod "$@"
''')
        before = self.snapshot()
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export', expected=1)
        self.assertEqual((self.status / 'message').read_text().strip(),
                         'Cannot expire previous recovery downloads')
        self.assertFalse((self.protected / 'transfers/abc123-456.json').exists())
        self.assertEqual(self.snapshot(), before)

    def test_export_allowlist_excludes_tokens_configs_history_and_logs(self):
        self.prep_live()
        self.account.parent.mkdir(parents=True)
        shutil.copy(self.private / 'live/key.pem', self.account)
        (self.private / 'prod-config/account.conf').write_text("SAVED_CF_Token='old_leaked_token_0987654321'\nACCOUNT_EMAIL='keep_out'\n")
        (self.private / 'sadleracme.log').write_text('hidden_log_token_123456789\n')
        (self.private / 'dsm-id').write_text('private_DSM_ID')
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export')
        path = self.protected / 'transfers/abc123-456.json'
        raw = path.read_text()
        for secret in (regression.TOKEN, 'old_leaked_token', 'hidden_log_token', 'private_DSM_ID', 'cf_token', 'account.conf'):
            self.assertNotIn(secret, raw)
        doc = json.loads(raw)
        self.assertEqual(doc['format'], 'SadlerACME')
        self.assertEqual(doc['settings']['auto_renew'], '0')
        self.assertEqual(set(doc['certificate']), {'key.pem', 'cert.pem', 'ca.pem', 'fullchain.pem'})
        self.assertIn('PRIVATE KEY', doc['acme_account_key'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.status / 'backup_download').read_text().strip(), 'abc123-456')
        self.assertNotIn('PRIVATE KEY', ''.join(p.read_text() for p in self.status.iterdir() if p.is_file()))
        commands = self.syslog.read_text().splitlines()
        self.assertIn('enable pkg-sadleracme-transfer-expire.timer', commands)
        self.assertIn('start pkg-sadleracme-transfer-expire.timer', commands)
        self.assertLess(commands.index('enable pkg-sadleracme-transfer-expire.timer'),
                        commands.index('start pkg-sadleracme-transfer-expire.timer'))
        self.assertEqual(json.loads(self.transfer_state.read_text()), dict(enabled=True, active=True))

    def test_settings_only_backup_and_restore(self):
        doc, _ = self.export(cert=False)
        self.assertIsNone(doc['certificate'])
        self.assertIsNone(doc['acme_account_key'])
        self.restore(doc)
        settings = json.loads((self.etc / 'settings.json').read_text())
        self.assertEqual(settings['auto_renew'], '0')
        self.assertEqual(settings['cf_token'], 'fresh_cloudflare_token_01234567890123456789')
        self.assertEqual((self.status / 'restore_requires_issue').read_text().strip(), 'yes')
        self.assertFalse((self.private / 'applied_signature').exists())

    def test_roundtrip_rebuilds_profile_without_hooks_or_dsm_mutation(self):
        doc, _ = self.export()
        old_cert = doc['certificate']['cert.pem']
        # Simulate a different existing installation before overwriting it.
        self.prep_live()
        (self.private / 'dsm-id').write_text('old-nas-id')
        (self.private / 'prod-config/account.conf').write_text("SAVED_CF_Token='old-token'\nLe_ReloadCmd='touch /never'\n")
        self.restore(doc)
        self.assertTrue((self.private / 'live').is_symlink())
        self.assertEqual((self.private / 'live/cert.pem').read_text(), old_cert)
        self.assertFalse((self.private / 'dsm-id').exists())
        self.assertFalse((self.private / 'prod-config/account.conf').exists())
        profile = (self.private / 'prod-certs/example.com_ecc/example.com.conf').read_text()
        self.assertIn("Le_Webroot='dns_cf'", profile)
        self.assertNotIn('Reload', profile)
        self.assertNotIn(regression.TOKEN, profile)
        self.assertTrue((self.private / 'applied_signature').exists())
        self.assertTrue(self.account.exists())
        self.assertFalse((self.private / 'recovery-transaction').exists())
        for line in (self.root / 'dsm-calls').read_text().splitlines():
            self.assertIn('method=list', line)
        self.assertFalse(self.syslog.read_text().count('restart MailPlus'))

    def test_expired_certificate_restores_but_requires_fresh_issuance(self):
        self.prep_live(expired=True)
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export')
        doc = json.loads((self.protected / 'transfers/abc123-456.json').read_text())
        self.restore(doc)
        self.assertFalse((self.private / 'applied_signature').exists())
        self.assertEqual((self.status / 'restore_requires_issue').read_text().strip(), 'yes')
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['auto_renew'], '0')

    def test_pending_saved_settings_backup_keeps_actual_certificate_metadata(self):
        self.prep_live()
        pending = dict(regression.CONFIG, domains=['new.example.com'], key_type='rsa-2048')
        (self.private / 'work/config.json').write_text(json.dumps(pending))
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export')
        doc = json.loads((self.protected / 'transfers/abc123-456.json').read_text())
        self.assertEqual(doc['settings']['domains'], ['new.example.com'])
        self.assertEqual(doc['settings']['key_type'], 'rsa-2048')
        self.assertEqual(sorted(doc['metadata']['domains']), sorted(regression.CONFIG['domains']))
        self.assertEqual(doc['metadata']['key_type'], 'ec-384')
        self.restore(doc)
        self.assertFalse((self.private / 'applied_signature').exists())
        self.assertEqual((self.status / 'restore_requires_issue').read_text().strip(), 'yes')
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['domains'], ['new.example.com'])
        self.assertEqual((self.private / 'live/cert.pem').read_text(), doc['certificate']['cert.pem'])

    def test_rejects_unknown_paths_hooks_and_embedded_credentials(self):
        doc, _ = self.export()
        before = self.snapshot()
        variants = []
        v = copy.deepcopy(doc); v['certificate']['../../owned'] = 'x'; variants.append(v)
        v = copy.deepcopy(doc); v['settings']['cf_token'] = regression.TOKEN; variants.append(v)
        v = copy.deepcopy(doc); v['account.conf'] = "touch /never"; variants.append(v)
        v = copy.deepcopy(doc); v['settings']['domains'] = ['example.com; touch /never']; variants.append(v)
        v = copy.deepcopy(doc); v['version'] = 2; variants.append(v)
        v = copy.deepcopy(doc); v['metadata']['key_type'] = 'rsa-2048'; variants.append(v)
        v = copy.deepcopy(doc); v['certificate']['key.pem'] = 'x' * 131073; variants.append(v)
        for value in variants:
            with self.subTest(value=str(value)[:50]):
                self.restore(value, expected=1)
                self.assertEqual(self.snapshot(), before)

    def test_rejects_mismatched_key_sans_and_chain_without_state_changes(self):
        doc, _ = self.export()
        before = self.snapshot()
        regression.certificate(self.private / 'different', domains=['other.example.com'])
        variants = []
        v = copy.deepcopy(doc); v['certificate']['key.pem'] = (self.private / 'different/key.pem').read_text(); variants.append(v)
        v = copy.deepcopy(doc); v['settings']['domains'] = ['other.example.com']; v['metadata']['domains'] = ['other.example.com']; variants.append(v)
        v = copy.deepcopy(doc); v['certificate']['fullchain.pem'] = v['certificate']['cert.pem']; variants.append(v)
        for value in variants:
            self.restore(value, expected=1)
            self.assertEqual(self.snapshot(), before)

    def test_restore_requires_new_token(self):
        doc, _ = self.export()
        before = self.snapshot()
        self.restore(doc, token='', expected=1)
        self.assertEqual(self.snapshot(), before)

    def test_failed_settings_commit_rolls_back_previous_certificate_and_settings(self):
        doc, _ = self.export()
        self.prep_live()
        (self.private / 'dsm-id').write_text('original-id')
        before = self.snapshot()
        self.restore(doc, extra='''
first_commit=1
commit_settings_from_file() {
  if [ "$first_commit" = 1 ]; then first_commit=0; return 1; fi
  cp "$1" "$ETC/settings.json"
}
''', expected=1)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.private / 'recovery-transaction').exists())

    def test_abandoned_download_expires_and_authenticated_acknowledgement_deletes(self):
        _, path = self.export(cert=False)
        os.utime(path, (time.time() - 901, time.time() - 901))
        self.shell('recovery_expire_transfers')
        self.assertFalse(path.exists())
        self.assertEqual((self.status / 'backup_download').read_text().strip(), '')
        self.assertEqual(json.loads(self.transfer_state.read_text()), dict(enabled=False, active=False))
        self.assertEqual(self.syslog.read_text().splitlines()[-2:], [
            'disable pkg-sadleracme-transfer-expire.timer',
            'stop pkg-sadleracme-transfer-expire.timer'])
        self.export(cert=False)
        (self.private / 'work/job.json').write_text(json.dumps(dict(transfer_id='abc123-456')))
        self.shell('backup_delete')
        self.assertFalse(path.exists())
        (self.private / 'work/job.json').write_text(json.dumps(dict(transfer_id='../private')))
        self.shell('backup_delete', expected=1)
        self.assertTrue(self.private.is_dir())

    def test_failed_restore_preserves_prior_legacy_migration_decision(self):
        doc, _ = self.export(cert=False)
        marker = self.private / 'migration-v1'
        for existing in (False, True):
            with self.subTest(marker_existed=existing):
                marker.unlink(missing_ok=True)
                if existing:
                    marker.write_text('prior migration completed\n')
                before = self.snapshot()
                self.restore(doc, extra='''
first_commit=1
commit_settings_from_file() {
  if [ "$first_commit" = 1 ]; then first_commit=0; return 1; fi
  cp "$1" "$ETC/settings.json"
}
''', expected=1)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.private / 'recovery-transaction').exists())

    def test_crashed_restore_restores_or_keeps_legacy_marker_at_commit_boundary(self):
        marker = self.private / 'migration-v1'
        for committed in (False, True):
            for existing in (False, True):
                with self.subTest(committed=committed, marker_existed=existing):
                    marker.unlink(missing_ok=True)
                    tx = self.private / 'recovery-transaction'
                    (tx / 'old').mkdir(parents=True)
                    (tx / 'started').touch()
                    (tx / 'settings-present').touch()
                    shutil.copy(self.etc / 'settings.json', tx / 'old-settings.json')
                    if existing:
                        (tx / 'old/migration-v1').write_text('prior migration completed\n')
                    else:
                        (tx / 'absent-migration-v1').touch()
                    marker.touch()
                    if committed:
                        (tx / 'committed').touch()
                    self.shell(self.commit + '\nrecovery_recover_transaction')
                    self.assertEqual(marker.exists(), committed or existing)
                    if marker.exists():
                        self.assertEqual(marker.read_text(), '' if committed else 'prior migration completed\n')
                    self.assertFalse(tx.exists())

    def test_expiry_timer_enable_start_and_activation_failures_leave_no_download(self):
        self.prep_live()
        before = self.snapshot()
        cases = [({'TEST_TRANSFER_TIMER_FAIL': 'enable'}, 'could not be enabled'),
                 ({'TEST_TRANSFER_TIMER_FAIL': 'start'}, 'could not be started'),
                 ({'TEST_TRANSFER_TIMER_INACTIVE_AFTER_START': '1'}, 'did not become active')]
        for env, message in cases:
            with self.subTest(env=env):
                self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export', env=env, expected=1)
                self.assertIn(message, (self.status / 'message').read_text())
                self.assertFalse((self.protected / 'transfers/abc123-456.json').exists())
                self.assertFalse((self.status / 'backup_download').exists())
                self.assertEqual(json.loads(self.transfer_state.read_text()), dict(enabled=False, active=False))
                self.assertEqual(self.snapshot(), before)

    def test_expiry_stops_timer_even_when_disabling_it_fails(self):
        _, path = self.export(cert=False)
        os.utime(path, (time.time() - 901, time.time() - 901))
        self.shell('recovery_expire_transfers', env={'TEST_TRANSFER_TIMER_FAIL': 'disable'})
        self.assertFalse(path.exists())
        self.assertEqual((self.status / 'backup_download').read_text().strip(), '')
        self.assertEqual(json.loads(self.transfer_state.read_text()), dict(enabled=True, active=False))
        self.assertEqual(self.syslog.read_text().splitlines()[-2:], [
            'disable pkg-sadleracme-transfer-expire.timer',
            'stop pkg-sadleracme-transfer-expire.timer'])

    def test_interrupted_restore_journal_recovers_before_further_work(self):
        self.prep_live()
        before = self.snapshot()
        tx = self.private / 'recovery-transaction'
        (tx / 'old').mkdir(parents=True)
        (tx / 'started').touch()
        (tx / 'settings-present').touch()
        shutil.copy(self.etc / 'settings.json', tx / 'old-settings.json')
        shutil.move(self.private / 'live', tx / 'old/live')
        self.prep_live()
        (self.etc / 'settings.json').write_text('{}')
        # Only live has moved; recovery must preserve untouched profile state.
        self.shell(self.commit + '\nrecovery_recover_transaction')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(tx.exists())

    def test_duplicate_dsm_descriptions_are_reported_without_import(self):
        doc, _ = self.export()
        self.set_list([dict(id='one', desc=regression.CONFIG['cert_desc']), dict(id='two', desc=regression.CONFIG['cert_desc'])])
        self.restore(doc)
        self.assertFalse((self.private / 'dsm-id').exists())
        self.assertIn('ambiguous', (self.status / 'message').read_text())
        self.assertNotIn('method=import', (self.root / 'dsm-calls').read_text())

    def test_changed_description_restores_existing_dsm_id_by_verified_fingerprint(self):
        doc, _ = self.export()
        archive = self.root / 'usr/syno/etc/certificate/_archive/original'
        archive.mkdir(parents=True)
        shutil.copy(self.private / 'live/cert.pem', archive / 'cert.pem')
        doc['settings']['cert_desc'] = 'New app description'
        self.set_list([dict(id='original', desc='Original DSM description', is_default=True)])
        self.restore(doc)
        self.assertEqual((self.private / 'dsm-id').read_text().strip(), 'original')
        self.assertEqual((self.status / 'dsm_match').read_text().strip(), 'yes')
        self.assertEqual((self.status / 'dsm_default').read_text().strip(), 'true')
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['cert_desc'], 'New app description')
        self.assertNotIn('method=import', (self.root / 'dsm-calls').read_text())

    def test_duplicate_fingerprints_do_not_choose_an_arbitrary_dsm_slot(self):
        doc, _ = self.export()
        for identifier in ('first', 'second'):
            archive = self.root / ('usr/syno/etc/certificate/_archive/' + identifier)
            archive.mkdir(parents=True)
            shutil.copy(self.private / 'live/cert.pem', archive / 'cert.pem')
        self.set_list([dict(id='first', desc='First description'), dict(id='second', desc='Second description')])
        self.restore(doc)
        self.assertFalse((self.private / 'dsm-id').exists())
        self.assertIn('ambiguous', (self.status / 'message').read_text())
        # The same lookup guard runs before subsequent ordinary issuance, so
        # ignoring the restore warning cannot accidentally create a third slot.
        self.shell('load_public_config\nlist_dsm_certificate', expected=2)
        self.assertFalse((self.private / 'dsm-id').exists())
        # Selecting one unique existing description resolves the ambiguity.
        self.shell('CERT_DESC="Second description"\nlist_dsm_certificate')
        self.assertEqual((self.private / 'dsm-id').read_text().strip(), 'second')

    def test_exact_description_ambiguity_is_not_bypassed_by_unique_fingerprint(self):
        doc, _ = self.export()
        archive = self.root / 'usr/syno/etc/certificate/_archive/one'
        archive.mkdir(parents=True)
        shutil.copy(self.private / 'live/cert.pem', archive / 'cert.pem')
        self.set_list([dict(id='one', desc=regression.CONFIG['cert_desc']), dict(id='two', desc=regression.CONFIG['cert_desc'])])
        self.restore(doc)
        self.assertFalse((self.private / 'dsm-id').exists())
        self.assertIn('ambiguous', (self.status / 'message').read_text())

    def test_failed_profile_copy_cannot_commit_a_partial_renewal_profile(self):
        doc, _ = self.export()
        before = self.snapshot()
        self.restore(doc, extra='''
cp() {
  case "$*" in *prod-certs*example.com.key*) return 1;; esac
  command cp "$@"
}
''', expected=1)
        self.assertEqual(self.snapshot(), before)

    def test_real_queued_restore_uses_configuration_guard_and_atomic_commit(self):
        doc, _ = self.export()
        saved = json.loads((self.etc / 'settings.json').read_text())
        settings_hash = hashlib.sha256((json.dumps(saved, sort_keys=True, separators=(',', ':')) + '\n').encode()).hexdigest()
        config = dict(regression.CONFIG, cf_token='new_worker_token_012345678901234567890')
        job = dict(action='restore', config=config, backup=doc, expected_settings_hash=settings_hash)
        (self.inbox / 'abcdef-1234.job').write_text(json.dumps(job))
        result = self.full_worker()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        settings = json.loads((self.etc / 'settings.json').read_text())
        self.assertEqual(settings['auto_renew'], '0')
        self.assertEqual(settings['cf_token'], config['cf_token'])
        self.assertEqual((self.etc / 'settings.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.private / 'live').is_symlink())
        self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'completed')
        before = self.snapshot()
        # A stale wizard from another tab cannot overwrite the committed state.
        (self.inbox / 'abcdef-5678.job').write_text(json.dumps(job))
        result = self.full_worker()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.snapshot(), before)
        self.assertIn('Settings changed', (self.status / 'message').read_text())


def load_tests(loader, tests, pattern):
    # Reuse fixture helpers, not the inherited baseline test methods.
    return unittest.TestSuite(Recovery(name) for name in sorted(Recovery.__dict__) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
