#!/usr/bin/env python3
"""Read-only renewal-deadline fixtures; no host systemd or NAS is accessed.

Exercise DSM 219-shaped list-timers output with real UTC date conversion.
Only the fixed systemctl query is mocked. No timer is started or rescheduled.
"""
import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TIMER = 'pkg-sadleracme-renew.timer'
SERVICE = 'pkg-sadleracme-renew.service'
QUERY = ['list-timers', '--all', '--no-pager', '--full']
STAMP = 'Mon 2026-09-28 19:16:27 UTC'
EPOCH = str(int(datetime.datetime(2026, 9, 28, 19, 16, 27, tzinfo=datetime.timezone.utc).timestamp()))
ROW = STAMP + ' 5h 59min left Mon 2026-09-28 13:16:27 UTC 1min ago ' + TIMER + ' ' + SERVICE


class TimerStatus(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='sadler-timer-status-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = self.root / 'private'
        self.status = self.root / 'status'
        self.bin = self.root / 'bin'
        for folder in (self.private, self.status, self.bin):
            folder.mkdir()
        self.running = self.root / 'package.running'
        self.running.touch()
        self.key = self.private / 'key.pem'
        self.key.write_text('fixture private certificate material')
        self.settings = self.root / 'settings.json'
        self.settings.write_text('{"auto_renew":"0"}')
        self.table = self.root / 'timer-table'
        self.table.write_text(ROW + '\n')
        self.calls = self.root / 'calls.jsonl'
        self.env = dict(os.environ, PATH=str(self.bin) + ':/usr/bin:/bin',
                        TIMER_TABLE=str(self.table), TIMER_CALLS=str(self.calls))
        self.executable(self.bin / 'systemctl', '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
with Path(os.environ['TIMER_CALLS']).open('a') as output:
    output.write(json.dumps({'args': sys.argv[1:], 'locale': os.environ.get('LC_ALL'), 'tz': os.environ.get('TZ')}) + '\\n')
if sys.argv[1:] != ['list-timers', '--all', '--no-pager', '--full']:
    raise SystemExit(91)
print(Path(os.environ['TIMER_TABLE']).read_text(), end='')
raise SystemExit(int(os.environ.get('TIMER_QUERY_RC', '0')))
''')
        self.script = ('set -eu\nRUN_MARKER=' + shlex.quote(str(self.running)) +
                       '\nROOT_STATE=' + shlex.quote(str(self.private)) +
                       '\nSTATUS_DIR=' + shlex.quote(str(self.status)) +
                       '\nwrite_public() { printf "%s\\n" "$2" > "$STATUS_DIR/$1"; }\n' +
                       (ROOT / 'src/lib/timer-status.sh').read_text())

    def executable(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def refresh(self, state='active', table=None, env=None, expected=EPOCH):
        if table is not None:
            self.table.write_text(table)
        self.calls.unlink(missing_ok=True)
        before = (self.key.read_bytes(), self.settings.read_bytes())
        result = subprocess.run(['sh', '-c', self.script + '\nrefresh_renewal_deadline ' + shlex.quote(state) + '\nprintf "continued\\n"'],
                                env=dict(self.env, **(env or {})), text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'continued\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual((self.status / 'next_auto_epoch').read_text().strip(), expected)
        self.assertEqual((self.key.read_bytes(), self.settings.read_bytes()), before)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        for call in calls:
            self.assertEqual(call, dict(args=QUERY, locale='C', tz='UTC'))
        self.assertLessEqual(len(calls), 1)
        return calls

    def test_deadline_available_before_any_scheduled_run(self):
        self.assertFalse((self.private / 'last_auto_check').exists())
        self.assertEqual(len(self.refresh()), 1)
        self.assertFalse((self.private / 'last_auto_check').exists())

    def test_disabled_setting_caches_deadline_for_enable_without_a_timer_change(self):
        self.refresh()
        self.settings.write_text('{"auto_renew":"1"}')
        self.assertEqual((self.status / 'next_auto_epoch').read_text().strip(), EPOCH)
        self.refresh()

    def test_relative_columns_and_other_units_do_not_change_selection(self):
        other = ROW.replace(TIMER, 'different.timer').replace(SERVICE, 'different.service')
        short = STAMP + ' 2s left n/a n/a ' + TIMER + ' ' + SERVICE
        self.refresh(table='NEXT LEFT LAST PASSED UNIT ACTIVATES\n' + other + '\n' + short + '\n2 timers listed.\n')

    def test_utc_conversion_is_independent_of_process_timezone(self):
        self.refresh(env=dict(TZ='Australia/Sydney', LANG='fr_FR.UTF-8'))

    def test_past_due_deadline_is_not_replaced_by_an_estimate(self):
        stamp = 'Thu 2020-01-02 03:04:05 UTC'
        epoch = str(int(datetime.datetime(2020, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc).timestamp()))
        self.refresh(table=stamp + ' 1s ago n/a n/a ' + TIMER + ' ' + SERVICE, expected=epoch)

    def test_missing_or_unavailable_next_clears_old_deadline(self):
        for table in ('', '0 timers listed.\n', 'n/a n/a n/a n/a ' + TIMER + ' ' + SERVICE,
                      '- - - - ' + TIMER + ' ' + SERVICE):
            with self.subTest(table=table):
                (self.status / 'next_auto_epoch').write_text(EPOCH)
                self.refresh(table=table, expected='')

    def test_wrong_service_or_truncated_unit_does_not_match(self):
        for table in (ROW.replace(SERVICE, 'different.service'), ROW.replace(TIMER, 'pkg-sadleracme-...'),
                      ROW.replace(TIMER, 'prefix-' + TIMER), ROW + ' unexpected-column'):
            with self.subTest(table=table):
                self.refresh(table=table, expected='')

    def test_duplicate_matching_rows_are_rejected(self):
        self.refresh(table=ROW + '\n' + ROW, expected='')

    def test_valid_and_unavailable_duplicate_is_rejected(self):
        self.refresh(table=ROW + '\nn/a n/a n/a n/a ' + TIMER + ' ' + SERVICE, expected='')

    def test_unrecognised_timestamp_format_is_rejected(self):
        for stamp in ('Mon 2026-09-28 19:16:27 AEST', 'Monday 2026-09-28 19:16:27 UTC',
                      'Mon 2026-9-28 19:16:27 UTC', 'Mon 2026-09-28 19:16 UTC',
                      'Mon 2026-09-28 19:16:27.123456 UTC', 'Mon 2026-09-28 19:16:27 UTC;echo'):
            with self.subTest(stamp=stamp):
                self.refresh(table=ROW.replace(STAMP, stamp), expected='')

    def test_invalid_date_or_wrong_weekday_is_rejected(self):
        for stamp in ('Mon 2026-02-30 19:16:27 UTC', 'Tue 2026-09-28 19:16:27 UTC',
                      'Mon 2026-09-28 25:16:27 UTC', 'Mon 2026-13-28 19:16:27 UTC'):
            with self.subTest(stamp=stamp):
                self.refresh(table=ROW.replace(STAMP, stamp), expected='')

    def test_failed_query_clears_deadline_even_if_stdout_looks_valid(self):
        (self.status / 'next_auto_epoch').write_text(EPOCH)
        self.refresh(env=dict(TIMER_QUERY_RC='1'), expected='')

    def test_failed_date_conversion_is_nonfatal(self):
        self.executable(self.bin / 'date', '#!/bin/sh\nexit 2\n')
        self.refresh(expected='')

    def test_non_numeric_date_output_is_nonfatal(self):
        self.executable(self.bin / 'date', '#!/bin/sh\nprintf "invalid epoch\\n"\n')
        self.refresh(expected='')

    def test_busybox_explicit_input_format_fallback(self):
        # This models the BusyBox command boundary using real GNU conversion;
        # it does not claim to execute a native DSM BusyBox binary.
        calls = self.root / 'date-calls.jsonl'
        self.executable(self.bin / 'date', '''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['DATE_CALLS']).open('a') as output:
    output.write(json.dumps({'args': args, 'locale': os.environ.get('LC_ALL'), 'tz': os.environ.get('TZ')}) + '\\n')
if '-D' not in args:
    raise SystemExit(1)
index = args.index('-D')
assert args[index + 1] == '%a %Y-%m-%d %H:%M:%S %Z'
del args[index:index + 2]
os.execv('/usr/bin/date', ['date'] + args)
''')
        self.refresh(env=dict(DATE_CALLS=str(calls)))
        attempts = [json.loads(line) for line in calls.read_text().splitlines()]
        self.assertEqual(len(attempts), 2)
        self.assertNotIn('-D', attempts[0]['args'])
        self.assertIn('-D', attempts[1]['args'])
        for attempt in attempts:
            self.assertEqual((attempt['locale'], attempt['tz']), ('C', 'UTC'))

    def test_normalized_date_mismatch_or_oversized_epoch_is_rejected(self):
        for value in ('Tue 2026-09-29 19:16:27 UTC|' + EPOCH,
                      STAMP + '|10000000000', STAMP + '|0', STAMP + '|-1'):
            with self.subTest(value=value):
                self.executable(self.bin / 'date', '#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(value) + '\n')
                self.refresh(expected='')

    def test_inactive_or_unknown_timer_clears_without_query(self):
        for state in ('inactive', 'failed', 'unknown', 'not-found', ''):
            with self.subTest(state=state):
                (self.status / 'next_auto_epoch').write_text(EPOCH)
                self.assertEqual(self.refresh(state=state, expected=''), [])

    def test_stopped_package_clears_without_query(self):
        self.running.unlink()
        self.assertEqual(self.refresh(expected=''), [])

    def test_temporary_setup_pending_apply_or_uninstall_clears_without_query(self):
        for marker in ('setup-temporary', 'wizard-apply.pending', 'uninstall-ready'):
            with self.subTest(marker=marker):
                flag = self.private / marker
                flag.touch()
                self.assertEqual(self.refresh(expected=''), [])
                flag.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
