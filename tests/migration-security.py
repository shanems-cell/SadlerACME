#!/usr/bin/env python3
"""Offline inode/ownership checks for legacy certificate migration.

All paths and race targets are synthetic temporary files. Ownership is modeled
by device/inode because the runner maps UID 0 only. Descriptor binding and path
replacement use real files. No live DSM keys, services, ACME, or network is used.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

spec = importlib.util.spec_from_file_location('migration_regression', Path(__file__).with_name('regression.py'))
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)

PACKAGE_UID = 65534


@unittest.skipUnless(os.geteuid() == 0, 'Synthetic ownership fixtures require local root')
class MigrationSecurity(regression.Regression):
    def setUp(self):
        super().setUp()
        self.owners = self.root / 'inode-owners.json'
        self.owners.write_text('{}')
        real_stat = shutil.which('stat')
        self.write_exe(self.bin / 'stat', '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ['-Lc', '%%u', '/proc/self/fd/5'] and os.environ.get('TEST_MIGRATION_SWAP_KEY'):
    marker = Path(os.environ['TEST_MIGRATION_SWAP_MARKER'])
    if not marker.exists():
        key = Path(os.environ['TEST_MIGRATION_SWAP_KEY'])
        key.rename(key.with_name('key.original'))
        key.symlink_to(os.environ['TEST_MIGRATION_SWAP_TARGET'])
        marker.touch()
if len(args) == 3 and args[0] in ('-Lc', '-c') and args[1] == '%%u':
    value = os.stat(args[2], follow_symlinks=args[0] == '-Lc')
    owners = json.loads(Path(%s).read_text())
    print(owners.get(str(value.st_dev) + ':' + str(value.st_ino), value.st_uid))
    sys.exit(0)
os.execv(%s, [%s] + args)
''' % (json.dumps(str(self.owners)), json.dumps(real_stat), json.dumps(real_stat)))

    def set_owner(self, path, uid):
        value = path.stat()
        owners = json.loads(self.owners.read_text())
        owners[str(value.st_dev) + ':' + str(value.st_ino)] = uid
        self.owners.write_text(json.dumps(owners))

    def legacy(self, *, package_files=True, writable_parent=True):
        path = self.var / 'root/live'
        regression.certificate(path)
        self.set_owner(self.etc, PACKAGE_UID)
        if writable_parent:
            self.set_owner(self.var, PACKAGE_UID)
        if package_files:
            for pem in path.glob('*.pem'):
                self.set_owner(pem, PACKAGE_UID)
        return path

    def assert_rejected(self):
        self.assertFalse((self.private / 'live').exists())
        self.assertFalse((self.private / 'live').is_symlink())
        self.assertFalse((self.private / 'migration-v1').exists())

    def test_package_owned_pems_migrate_from_package_writable_storage(self):
        path = self.legacy()
        original = (path / 'key.pem').read_bytes()
        self.shell('migrate_legacy_live')
        self.assertEqual((self.private / 'live/key.pem').read_bytes(), original)
        self.assertEqual((path / 'key.pem').read_bytes(), original)
        self.assertTrue((self.private / 'migration-v1').exists())

    def test_protected_root_owned_legacy_remains_supported(self):
        path = self.legacy(package_files=False, writable_parent=False)
        self.shell('migrate_legacy_live')
        self.assertEqual((self.private / 'live/key.pem').read_bytes(), (path / 'key.pem').read_bytes())

    def test_root_owned_pem_below_package_parent_requires_manual_recovery(self):
        path = self.legacy(package_files=False)
        original = (path / 'key.pem').read_bytes()
        self.shell('migrate_legacy_live', expected=1)
        self.assert_rejected()
        self.assertIn('administrator-assisted manual recovery', (self.status / 'message').read_text())
        self.assertEqual((path / 'key.pem').read_bytes(), original)
        self.assertEqual(list(self.private.glob('live-gen.*/key.pem')), [])

    def test_other_account_owned_pem_is_rejected(self):
        path = self.legacy()
        self.set_owner(path / 'key.pem', PACKAGE_UID - 1)
        self.shell('migrate_legacy_live', expected=1)
        self.assert_rejected()

    def test_source_symlink_and_fifo_are_rejected_without_copy(self):
        path = self.legacy()
        target = self.private / 'unrelated-private-key'
        target.write_text('unrelated root-owned fixture data\n')
        key = path / 'key.pem'
        key.unlink()
        key.symlink_to(target)
        self.shell('migrate_legacy_live', expected=1)
        self.assert_rejected()
        key.unlink()
        os.mkfifo(key)
        self.shell('migrate_legacy_live', expected=1)
        self.assert_rejected()
        self.assertEqual(target.read_text(), 'unrelated root-owned fixture data\n')

    def test_path_replacement_after_open_copies_only_the_bound_package_inode(self):
        path = self.legacy()
        key = path / 'key.pem'
        original = key.read_bytes()
        target = self.private / 'unrelated-private-key'
        target.write_text('unrelated root-owned fixture data\n')
        marker = self.root / 'source-swapped'
        # Interpose only on the exact inode-owner query, after the worker has
        # opened FD5. The replacement must never affect its subsequent copy.
        self.shell('migrate_legacy_live', env=dict(TEST_MIGRATION_SWAP_KEY=str(key),
                                                TEST_MIGRATION_SWAP_TARGET=str(target),
                                                TEST_MIGRATION_SWAP_MARKER=str(marker)))
        self.assertTrue(marker.exists())
        self.assertTrue(key.is_symlink())
        self.assertEqual((self.private / 'live/key.pem').read_bytes(), original)
        self.assertEqual(target.read_text(), 'unrelated root-owned fixture data\n')

    def test_oversized_source_is_rejected_before_copy(self):
        path = self.legacy()
        with (path / 'key.pem').open('ab') as source:
            source.write(b'X' * 131072)
        self.shell('migrate_legacy_live', expected=1)
        self.assert_rejected()
        self.assertEqual(list(self.private.glob('live-gen.*/key.pem')), [])



class LegacyRecoveryEntryPoints(MigrationSecurity):
    """Exercise the assembled worker entry point, including real initialisation.

    Only DSM APIs/services and inode ownership are simulated. Migration,
    configuration locking, queue claiming, backup validation, restore, lease
    cleanup and uninstall preparation execute their production implementations.
    """
    def setUp(self):
        super().setUp()
        self.unit_state = self.root / 'unit-state.json'
        self.unit_state.write_text('{}')
        self.unit_log = self.root / 'unit-calls.jsonl'
        self.task_rows = self.root / 'scheduler-tasks.json'
        self.task_rows.write_text('[]')
        self.env.update(TEST_UNITS=str(self.unit_state), TEST_UNIT_LOG=str(self.unit_log),
                        TEST_TASKS=str(self.task_rows))
        self.write_exe(self.bin / 'systemctl', '#!' + sys.executable + '\n' + r'''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['TEST_UNIT_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
if '--now' in args:
    print('systemd 219 fixture rejects --now', file=sys.stderr)
    sys.exit(2)
path = Path(os.environ['TEST_UNITS'])
state = json.loads(path.read_text())
command = args[0]
if command in ('start', 'restart', 'stop'):
    for unit in args[1:]: state[unit] = 'inactive' if command == 'stop' else 'active'
elif command == 'show':
    active = state.get(args[1], 'inactive')
    print(active if '--value' in args else 'LoadState=loaded\nActiveState=' + active)
elif command == 'is-active':
    active = state.get(args[1], 'inactive')
    print(active)
    sys.exit(0 if active == 'active' else 3)
elif command not in ('enable', 'disable', 'daemon-reload'):
    print('Unexpected systemctl fixture command: ' + command, file=sys.stderr)
    sys.exit(90)
path.write_text(json.dumps(state))
''')
        self.write_exe(self.bin / 'sqlite3', '#!' + sys.executable + '\n' + r'''import json, os, sys
rows = json.load(open(os.environ['TEST_TASKS']))
sql = sys.argv[-1]
if sql.startswith('SELECT enable,'):
    rows = [row[1:] for row in rows if row[0] == 'SadlerACME Bootstrap']
for row in rows: print('|'.join(str(value) for value in row))
''')
        # Reachability tests must never issue, import, reload, or download. Only
        # the actual read-only DSM inventory call is accepted by this fixture.
        self.dsm_log = self.root / 'dsm-calls'
        self.write_exe(self.root / 'usr/syno/bin/synowebapi', f'''#!/bin/sh
printf '%s\\n' "$*" >> '{self.dsm_log}'
case "$*" in *api=SYNO.Core.Certificate.CRT*method=list*) cat '{self.listfile}';; *) exit 91;; esac
''')
        self.write_exe(self.root / 'usr/syno/bin/synow3tool', '#!/bin/sh\nexit 92\n')
        self.write_exe(self.bin / 'curl', '#!/bin/sh\nexit 93\n')
        (self.root / 'usr/local/lib/systemd/system').mkdir(parents=True)

    def setup_task(self):
        self.task_rows.write_text(json.dumps([['SadlerACME Setup', 0, 'bootup', 0,
            '/bin/systemctl start pkg-sadleracme-setup.service', 'script']]))

    def blank_settings(self):
        saved = dict(regression.CONFIG, email='', domains=[], cf_token='', auto_renew='0')
        (self.etc / 'settings.json').write_text(json.dumps(saved))
        return saved

    def run_full(self, action='worker', expected=0):
        result = self.full_worker(action)
        message = (self.status / 'message').read_text() if (self.status / 'message').exists() else ''
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout + message)
        self.assertTrue((self.status / 'worker_last_seen').is_file())
        return result

    def enqueue(self, action, *, config=None, **extra):
        job = dict(action=action, config=config if config is not None else regression.CONFIG, **extra)
        (self.inbox / 'abcdef-1234.job').write_text(json.dumps(job))

    def source_snapshot(self, source):
        return {p.name: p.read_bytes() for p in source.glob('*.pem')}

    def assert_legacy_untouched(self, source, snapshot):
        self.assertEqual(self.source_snapshot(source), snapshot)
        self.assert_rejected()
        self.assertEqual(list(self.private.glob('live-gen.*/key.pem')), [])

    def test_clean_temporary_setup_uses_blank_saved_settings(self):
        self.blank_settings()
        self.setup_task()
        # Start from no protected state, not the helper fixture's pre-created
        # private/status/inbox directories or work/config.json.
        shutil.rmtree(self.protected)
        self.run_full('systemd-setup')
        state = json.loads(self.unit_state.read_text())
        self.assertEqual(state['pkg-sadleracme-queue.path'], 'active')
        self.assertEqual(state['pkg-sadleracme-renew.timer'], 'inactive')
        self.assertEqual(state['pkg-sadleracme-setup-expire.timer'], 'active')
        self.assertEqual((self.status / 'setup_temporary').read_text().strip(), 'yes')
        self.assert_rejected()
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['cf_token'], '')

    def test_untrusted_legacy_does_not_block_temporary_or_permanent_startup(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        self.blank_settings()
        self.setup_task()
        self.run_full('systemd-setup')
        self.assert_legacy_untouched(source, snapshot)
        self.assertEqual((self.status / 'setup_temporary').read_text().strip(), 'yes')
        self.run_full('systemd-bootstrap')
        self.assert_legacy_untouched(source, snapshot)
        self.assertEqual((self.status / 'setup_temporary').read_text().strip(), 'no')
        state = json.loads(self.unit_state.read_text())
        self.assertEqual(state['pkg-sadleracme-queue.path'], 'active')
        self.assertEqual(state['pkg-sadleracme-renew.timer'], 'active')

    def test_status_actions_consume_queue_without_migrating_untrusted_source(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        for action in ('scheduler-status', 'refresh'):
            with self.subTest(action=action):
                self.enqueue(action)
                self.run_full()
                self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'completed')
                self.assert_legacy_untouched(source, snapshot)

    def test_every_certificate_action_still_rejects_untrusted_source(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        for action in ('test', 'apply', 'check', 'force', 'redeploy', 'wizard-test', 'wizard-apply', 'backup'):
            with self.subTest(action=action):
                self.enqueue(action)
                self.run_full(expected=1)
                self.assertEqual((self.status / 'last_action').read_text().strip(), 'migration')
                self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'failed')
                self.assertIn('administrator-assisted manual recovery', (self.status / 'message').read_text())
                self.assert_legacy_untouched(source, snapshot)
        self.assertFalse(self.dsm_log.exists())
        self.assertFalse((self.protected / 'transfers').exists())

    def test_automatic_renewal_retains_migration_guard_when_enabled(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        self.run_full('scheduled', expected=1)
        self.assertEqual((self.status / 'last_action').read_text().strip(), 'migration')
        self.assert_legacy_untouched(source, snapshot)

    def test_disabled_or_temporary_renewal_does_not_attempt_migration(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        (self.etc / 'settings.json').write_text(json.dumps(dict(regression.CONFIG, auto_renew='0')))
        self.run_full('scheduled')
        self.assert_legacy_untouched(source, snapshot)
        self.assertFalse((self.status / 'next_auto_epoch').read_text().strip())
        (self.etc / 'settings.json').write_text(json.dumps(regression.CONFIG))
        (self.private / 'setup-temporary').write_text('9999999999\n')
        self.run_full('scheduled')
        self.assert_legacy_untouched(source, snapshot)

    def test_package_owned_legacy_is_still_migrated_before_queued_backup(self):
        source = self.legacy()
        snapshot = self.source_snapshot(source)
        self.enqueue('backup')
        self.run_full()
        doc = json.loads((self.protected / 'transfers/abcdef-1234.json').read_text())
        self.assertEqual(doc['certificate']['cert.pem'], snapshot['cert.pem'].decode())
        self.assertEqual((self.private / 'live/key.pem').read_bytes(), snapshot['key.pem'])
        self.assertTrue((self.private / 'migration-v1').exists())
        self.assertEqual(self.source_snapshot(source), snapshot)
        self.assertNotIn('cf_token', doc['settings'])

    def test_real_queued_restore_bypasses_legacy_source_and_restores_validated_backup(self):
        # Produce the recovery document through the real exporter from a
        # different protected certificate, then simulate a fresh reinstall.
        self.prep_live()
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export')
        doc = json.loads((self.protected / 'transfers/abc123-456.json').read_text())
        shutil.rmtree(self.private / 'live')
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        saved = self.blank_settings()
        settings_hash = hashlib.sha256((json.dumps(saved, sort_keys=True, separators=(',', ':')) + '\n').encode()).hexdigest()
        fresh_config = dict(regression.CONFIG, cf_token='new_worker_token_012345678901234567890')
        self.enqueue('restore', config=fresh_config, backup=doc, expected_settings_hash=settings_hash)
        self.run_full()
        self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'completed')
        self.assertEqual((self.private / 'live/cert.pem').read_text(), doc['certificate']['cert.pem'])
        self.assertNotEqual((self.private / 'live/cert.pem').read_bytes(), snapshot['cert.pem'])
        self.assertEqual(self.source_snapshot(source), snapshot)
        self.assertTrue((self.private / 'migration-v1').exists())
        saved = json.loads((self.etc / 'settings.json').read_text())
        self.assertEqual(saved['cf_token'], fresh_config['cf_token'])
        self.assertEqual(saved['auto_renew'], '0')
        self.assertEqual((self.etc / 'settings.json').stat().st_mode & 0o777, 0o600)
        self.assertIn('without issuing or deploying', (self.status / 'message').read_text())
        for call in self.dsm_log.read_text().splitlines():
            self.assertIn('method=list', call)

    def test_settings_only_restore_supersedes_legacy_on_later_certificate_dispatch(self):
        self.shell('ACTIVE_JOB=abc123-456.job\nbackup_export')
        doc = json.loads((self.protected / 'transfers/abc123-456.json').read_text())
        self.assertIsNone(doc['certificate'])
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        saved = self.blank_settings()
        settings_hash = hashlib.sha256((json.dumps(saved, sort_keys=True, separators=(',', ':')) + '\n').encode()).hexdigest()
        fresh_config = dict(regression.CONFIG, cf_token='new_worker_token_012345678901234567890')
        self.enqueue('restore', config=fresh_config, backup=doc, expected_settings_hash=settings_hash)
        self.run_full()
        self.assertTrue((self.private / 'migration-v1').exists())
        self.assertFalse((self.private / 'live').exists())
        self.assertEqual((self.status / 'restore_requires_issue').read_text().strip(), 'yes')
        # A second full-worker run enters the common certificate-operation
        # migration guard. A real backup must still be settings-only; neither
        # an unsafe-source rejection nor automatic resurrection is acceptable.
        self.enqueue('backup', config=fresh_config)
        self.run_full()
        exported = json.loads((self.protected / 'transfers/abcdef-1234.json').read_text())
        self.assertIsNone(exported['certificate'])
        self.assertFalse((self.private / 'live').exists())
        self.assertEqual(list(self.private.glob('live-gen.*/key.pem')), [])
        self.assertEqual(self.source_snapshot(source), snapshot)

    def test_queued_cancel_and_preparation_remain_usable_with_untrusted_source(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        (self.private / 'setup-temporary').write_text('9999999999\n')
        self.unit_state.write_text(json.dumps({'pkg-sadleracme-queue.path': 'active',
                                              'pkg-sadleracme-setup-expire.timer': 'active'}))
        # DSM task removal already completed; only worker cleanup remains.
        self.enqueue('cancel-setup')
        self.run_full()
        self.assertFalse((self.private / 'setup-temporary').exists())
        self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'completed')
        self.assert_legacy_untouched(source, snapshot)
        self.enqueue('prepare-uninstall')
        self.run_full()
        self.assertTrue((self.private / 'uninstall-ready').is_file())
        self.assertEqual((self.status / 'uninstall_ready').read_text().strip(), 'yes')
        self.assertEqual((self.status / 'last_job_result').read_text().strip(), 'completed')
        self.assert_legacy_untouched(source, snapshot)
        self.assertEqual(json.loads(self.unit_state.read_text())['sadleracme-cleanup.service'], 'active')

    def test_expired_setup_can_stop_with_untrusted_legacy_source(self):
        source = self.legacy(package_files=False)
        snapshot = self.source_snapshot(source)
        (self.private / 'setup-temporary').write_text('1\n')
        self.unit_state.write_text(json.dumps({'pkg-sadleracme-queue.path': 'active'}))
        self.run_full('setup-expired')
        self.assertFalse((self.private / 'setup-temporary').exists())
        self.assertEqual(json.loads(self.unit_state.read_text())['pkg-sadleracme-queue.path'], 'inactive')
        self.assert_legacy_untouched(source, snapshot)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(name) for cls in (MigrationSecurity, LegacyRecoveryEntryPoints)
                              for name in sorted(cls.__dict__) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
