#!/usr/bin/env python3
"""File-backed SQLite integration tests for the real scheduler reader functions.

Default: requires the native sqlite3 command-line program. Set
SADLERACME_TEST_SQLITE to its path if it is not on PATH.

--python-sqlite-adapter: explicitly selects a narrow CLI adapter over Python's
real SQLite binding. This exercises actual file locks/read-only database access
and production shell functions, but DOES NOT validate native sqlite3 CLI option
compatibility. The backend and version are always printed in the transcript.
No DSM paths, actual services, or user certificates are touched.
"""
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOT_COMMAND = '/bin/systemctl start pkg-sadleracme-bootstrap.service'
BOOT = ('SadlerACME Bootstrap', 1, 'bootup', 0, BOOT_COMMAND, 'script')
BOOT_ROW = '|'.join(map(str, BOOT)) + '\n'
DB_PATH = '/usr/syno/etc/esynoscheduler/esynoscheduler.db'
USE_ADAPTER = '--python-sqlite-adapter' in sys.argv
if USE_ADAPTER:
    sys.argv.remove('--python-sqlite-adapter')
NATIVE = os.environ.get('SADLERACME_TEST_SQLITE') or shutil.which('sqlite3')
if not USE_ADAPTER and not NATIVE:
    sys.exit('Native sqlite3 CLI unavailable; no tests run. Install it or explicitly '
             'select --python-sqlite-adapter (limited CLI coverage).')
if USE_ADAPTER:
    print('BACKEND: Python SQLite ' + sqlite3.sqlite_version +
          ' with explicit CLI adapter; native sqlite3 flags NOT verified', flush=True)
else:
    version = subprocess.check_output([NATIVE, '-version'], text=True).strip()
    print('BACKEND: native sqlite3 CLI ' + str(NATIVE) + '\nVERSION: ' + version, flush=True)

# These columns/order/constraints mirror the table_info response supplied by DSM.
SCHEMA = '''CREATE TABLE task (
 task_name TEXT NOT NULL PRIMARY KEY,
 description TEXT,
 event TEXT NOT NULL,
 depend_on_task TEXT,
 enable INTEGER DEFAULT 1,
 owner INTEGER NOT NULL,
 run_the_same_time INTEGER DEFAULT 1,
 notify_enable INTEGER DEFAULT 0,
 notify_mail TEXT,
 notify_if_error INTEGER DEFAULT 0,
 operation TEXT NOT NULL,
 operation_type TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT '{}',
 last_start_time INTEGER,
 last_stop_time INTEGER,
 last_exit_info TEXT,
 extra TEXT DEFAULT '{}'
);'''
ADAPTER = '''#!PYTHON
import sqlite3, sys
from pathlib import Path
args = sys.argv[1:]
assert len(args) == 7 and args[:3] == ['-readonly', '-cmd', '.timeout 5000'], args
assert args[3:5] == ['-separator', '|'], args
try:
    connection = sqlite3.connect(Path(args[5]).resolve().as_uri() + '?mode=ro',
                                 uri=True, timeout=5.0)
    for row in connection.execute(args[6]):
        print('|'.join('' if value is None else str(value) for value in row))
    connection.close()
except sqlite3.Error as error:
    print('Error: ' + str(error), file=sys.stderr)
    sys.exit(getattr(error, 'sqlite_errorcode', 1) & 255)
'''


class SchedulerSQLite(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sadler-sqlite-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir(mode=0o700)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.db = self.root / 'scheduler.db'
        self.mutations = self.root / 'mutations'
        self.status_updates = self.root / 'status-updates'
        self.logs = self.root / 'logs'
        self.inbox = self.root / 'inbox'
        self.inbox.mkdir(mode=0o700)
        self.kept = self.root / 'certificate-and-settings-sentinel'
        self.kept.write_text('must remain untouched')
        if USE_ADAPTER:
            command = self.bin / 'sqlite3'
            command.write_text(ADAPTER.replace('#!PYTHON', '#!' + sys.executable, 1))
            command.chmod(0o755)
        else:
            (self.bin / 'sqlite3').symlink_to(Path(NATIVE).resolve())
        self.env = dict(os.environ, PATH=str(self.bin) + ':/usr/bin:/bin',
                        WORK=str(self.work), MUTATIONS=str(self.mutations),
                        INBOX=str(self.inbox), STATUS_UPDATES=str(self.status_updates),
                        LOGS=str(self.logs))
        source = (ROOT / 'src/lib/lifecycle.sh').read_text()
        self.assertIn("sr_db='" + DB_PATH + "'", source)
        source = source.replace(DB_PATH, str(self.db))
        self.functions = self.root / 'functions.sh'
        self.functions.write_text(source + '''
# Stub effects only: actual scheduler_read_rows/lifecycle_tasks/finish_setup above.
SCHED_BOOT_COMMAND='/bin/systemctl start pkg-sadleracme-bootstrap.service'
fail() { printf '%s\\n' "$1" >&2; exit 1; }
lifecycle_resume() { printf 'resume\\n' >> "$MUTATIONS"; }
systemctl() { printf 'systemctl %s\\n' "$*" >> "$MUTATIONS"; }
scheduler_status() { :; }
systemd_unit_state() { printf 'active\\n'; }
write_status() { printf 'status %s\\n' "$*" >> "$STATUS_UPDATES"; }
log() { printf '%s\\n' "$*" >> "$LOGS"; }
''')
        self.make_database()
        self.add_row(BOOT)

    def make_database(self, duplicate_names=False):
        self.db.unlink(missing_ok=True)
        with sqlite3.connect(self.db) as db:
            db.execute(SCHEMA.replace(' PRIMARY KEY', '') if duplicate_names else SCHEMA)

    def add_row(self, row):
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO task(task_name,enable,event,owner,operation,operation_type) '
                       'VALUES(?,?,?,?,?,?)', row)

    def run_shell(self, body, expected=0):
        started = time.monotonic()
        result = subprocess.run(['/bin/sh', '-c',
                                 'set -eu\numask 077\n. "$1"\n' + body,
                                 'scheduler-test', str(self.functions)],
                                capture_output=True, text=True, env=self.env, timeout=9)
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result, elapsed

    def no_mutations(self):
        self.assertFalse(self.mutations.exists())
        self.assertEqual(self.kept.read_text(), 'must remain untouched')
        self.assertEqual(self.inbox.stat().st_mode & 0o7777, 0o700)

    def digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def lock(self):
        connection = sqlite3.connect(self.db, check_same_thread=False)
        connection.execute('BEGIN EXCLUSIVE')
        return connection

    def test_real_table_returns_exact_filtered_rows_without_writing(self):
        self.add_row(('Unrelated task', 1, 'bootup', 0, '/bin/true', 'script'))
        before = self.digest()
        result, elapsed = self.run_shell('lifecycle_task_rows')
        self.assertEqual(result.stdout, BOOT_ROW)
        self.assertEqual(result.stderr, '')
        self.assertLess(elapsed, 2)
        self.assertEqual(self.digest(), before)
        self.no_mutations()

    def test_exclusive_lock_released_within_timeout_waits_then_finishes(self):
        before = self.digest()
        connection = self.lock()
        def release():
            connection.rollback()
            connection.close()
        timer = threading.Timer(0.7, release)
        timer.start()
        try:
            result, elapsed = self.run_shell('lifecycle_task_rows; finish_setup')
        finally:
            timer.join()
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertLess(elapsed, 4)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, BOOT_ROW)
        self.assertIn('Setup complete; permanent automation is ready', self.status_updates.read_text())
        self.assertEqual(self.digest(), before)
        self.assertEqual(self.kept.read_text(), 'must remain untouched')

    def test_persistent_lock_times_out_without_mutation_then_retry_succeeds(self):
        before = self.digest()
        connection = self.lock()
        try:
            result, elapsed = self.run_shell('finish_setup', expected=1)
            self.assertGreaterEqual(elapsed, 4.5)
            self.assertLess(elapsed, 8)
            self.assertIn('busy/locked (exit 5)', result.stderr)
            self.assertNotIn(str(self.db), result.stderr)
            self.no_mutations()
            self.assertEqual((self.work / 'scheduler-read.stderr').stat().st_mode & 0o777, 0o600)
        finally:
            connection.rollback()
            connection.close()
        retried, _ = self.run_shell('finish_setup')
        self.assertEqual(retried.stderr, '')
        self.assertEqual((self.work / 'scheduler-read.diagnostic').read_text(), '')
        self.assertEqual(self.digest(), before)

    def test_missing_schema_fails_immediately_with_fixed_diagnostic(self):
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TABLE task')
        result, elapsed = self.run_shell('finish_setup', expected=1)
        self.assertIn('schema (exit 1)', result.stderr)
        self.assertNotIn('no such table', result.stderr)
        self.assertLess(elapsed, 2)
        self.no_mutations()

    def test_raw_sqlite_error_is_kept_private_and_not_in_public_diagnostic(self):
        marker = 'private_test_marker_do_not_publish'
        result, _ = self.run_shell(
            "if scheduler_read_rows 'SELECT " + marker + " FROM task'; then exit 22; "
            'else scheduler_read_diagnostic; fi')
        self.assertEqual(result.stdout, 'schema (exit 1)\n')
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertIn(marker, (self.work / 'scheduler-read.stderr').read_text())
        self.no_mutations()

    def test_missing_database_is_not_created(self):
        self.db.unlink()
        result, elapsed = self.run_shell('finish_setup', expected=1)
        self.assertIn('access/open (exit 1)', result.stderr)
        self.assertFalse(self.db.exists())
        self.assertLess(elapsed, 2)
        self.no_mutations()

    def test_reader_rejects_write_query(self):
        before = self.digest()
        result, _ = self.run_shell(
            "if scheduler_read_rows 'DELETE FROM task'; then exit 22; "
            'else scheduler_read_diagnostic; fi')
        self.assertIn('(exit 8)', result.stdout)
        self.assertEqual(self.digest(), before)
        self.no_mutations()

    def test_duplicate_bootstrap_names_remain_rejected(self):
        # An adversarial altered schema deliberately permits duplicate names.
        self.make_database(duplicate_names=True)
        self.add_row(BOOT)
        self.add_row(BOOT)
        result, _ = self.run_shell('finish_setup', expected=1)
        self.assertIn('Install one enabled', result.stderr)
        self.no_mutations()

    def test_wrong_task_details_remain_rejected(self):
        for field, value in ((0, 'Unexpected duplicate'), (1, 0), (2, 'shutdown'),
                             (3, 1027), (4, '/bin/false'), (5, 'other')):
            with self.subTest(field=field, value=value):
                self.make_database()
                row = list(BOOT)
                row[field] = value
                self.add_row(row)
                result, _ = self.run_shell('finish_setup', expected=1)
                self.assertIn('Install one enabled', result.stderr)
                self.no_mutations()

    def test_remaining_setup_task_prevents_finish(self):
        self.add_row(('SadlerACME Setup', 0, 'bootup', 0,
                      '/bin/systemctl start pkg-sadleracme-setup.service', 'script'))
        result, _ = self.run_shell('finish_setup', expected=1)
        self.assertIn('Install one enabled', result.stderr)
        self.no_mutations()


if __name__ == '__main__':
    unittest.main(verbosity=2)
