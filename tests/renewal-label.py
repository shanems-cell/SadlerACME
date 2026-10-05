#!/usr/bin/env python3
"""Offline dashboard status fixtures; no NAS, systemd or network is accessed."""
import errno
import html as html_parser
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import unittest

spec = importlib.util.spec_from_file_location('label_regression', Path(__file__).with_name('regression.py'))
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)
EPOCH = str(int(time.time()) + 21600)


class RenewalLabel(regression.Regression):
    def publish(self, **fields):
        for name, value in fields.items():
            (self.status / name).write_text(value)

    def status_data(self):
        return json.loads(self.request(query='api=status').split('\n\n', 1)[1])

    def ui_fixture(self, data=None, **options):
        html = self.request()
        initial = {match.group(1): html_parser.unescape(match.group(2))
                   for match in re.finditer(r'<[^>]+\bid="([^"]+)"[^>]*>([^<]*)', html)}
        next_node = re.search(r'<span id="nextAuto"([^>]*)>', html)
        fixture = dict(html=html, script=re.search(r'<script>(.*?)</script>', html, re.S).group(1),
                       csrf=next(self.etc.glob('ui_csrf.*')).read_text(), initialText=initial,
                       attributes=dict(nextAuto=dict(re.findall(r'([\w-]+)="([^"]*)"', next_node.group(1)))),
                       status=self.status_data() if data is None else data, exerciseActions=False)
        fixture.update(options)
        return fixture

    def run_ui(self, fixture):
        result = subprocess.run(['node', str(regression.ROOT / 'tests/session-ui.js')],
                                input=json.dumps(fixture), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_label(self, label, next_text=None, next_epoch=None):
        data = self.status_data()
        self.assertEqual(data['auto_renew_text'], label)
        html = self.request()
        self.assertRegex(html, r'id="autoRenew"[^>]*>' + re.escape(label) + r'</div>')
        node = re.search(r'<span id="nextAuto"([^>]*)>([^<]*)</span>', html)
        fixture = self.ui_fixture(data, expectedText=dict(autoRenew=label))
        if next_text is not None:
            self.assertEqual(node.group(2), next_text)
            fixture['expectedInitialNextText'] = next_text
            fixture['expectedText']['nextAuto'] = next_text
        if next_epoch is not None:
            self.assertEqual(data['next_auto'], next_epoch)
            fixture['expectedInitialNextEpoch'] = next_epoch
            fixture['expectedNextEpoch'] = next_epoch
        self.run_ui(fixture)
        return data

    def active(self):
        self.publish(systemd_timer_state='active', systemd_queue_state='active',
                     scheduler_status='Installed and enabled', next_auto_epoch=EPOCH)

    def test_fresh_install_enabled_preference_needs_setup(self):
        data = self.assert_label('Enabled — setup required', next_text='Waiting for timer status')
        self.assertEqual(data['auto_renew'], '1')
        self.assertEqual(data['timer_state'], 'Unknown')

    def test_active_permanent_automation_shows_interval_and_deadline(self):
        self.active()
        self.assert_label('Enabled — every 6 hours', next_epoch=EPOCH)

    def test_disabled_preference_hides_cached_active_deadline(self):
        self.active()
        (self.etc / 'settings.json').write_text(json.dumps(dict(regression.CONFIG, auto_renew='0')))
        data = self.assert_label('Disabled', next_text='Disabled')
        self.assertEqual(data['next_auto'], '')

    def test_stopped_package_does_not_claim_running_automation_from_cached_status(self):
        self.active()
        (self.var / 'package.running').unlink()
        self.assert_label('Enabled — package stopped')

    def test_inactive_and_failed_timer_are_reported(self):
        self.active()
        for state in ('inactive', 'failed'):
            with self.subTest(state=state):
                self.publish(systemd_timer_state=state)
                self.assert_label('Enabled — timer ' + state, next_text='Timer ' + state)

    def test_temporary_setup_and_prepared_removal_do_not_claim_running_automation(self):
        self.active()
        self.publish(setup_temporary='yes')
        self.assert_label('Enabled — setup required')
        self.publish(setup_temporary='no', uninstall_ready='yes')
        self.assert_label('Enabled — paused for removal')

    def test_disabled_bootstrap_does_not_hide_current_active_timer(self):
        self.active()
        self.publish(scheduler_status='Installed but disabled')
        self.assert_label('Enabled — boot task disabled', next_epoch=EPOCH)

    def test_active_timer_requires_queue_and_verified_startup_for_ready_label(self):
        self.active()
        for state in ('inactive', 'failed', 'Unknown'):
            with self.subTest(queue=state):
                self.publish(systemd_queue_state=state)
                label = 'Enabled — queue ' + (state if state != 'Unknown' else 'status unknown')
                self.assert_label(label, next_epoch=EPOCH)
        self.publish(systemd_queue_state='active', scheduler_status='Unable to inspect')
        self.assert_label('Enabled — startup unverified', next_epoch=EPOCH)
        self.publish(scheduler_status='Missing')
        self.assert_label('Enabled — setup required', next_epoch=EPOCH)

    def test_worker_available_requires_running_package_and_queue_directory(self):
        data = self.status_data()
        self.assertEqual((data['package_running'], data['worker_available']), ('yes', 'yes'))
        (self.var / 'package.running').unlink()
        data = self.status_data()
        self.assertEqual((data['package_running'], data['worker_available']), ('no', 'no'))
        (self.var / 'package.running').touch()
        self.inbox.rmdir()
        self.assertEqual(self.status_data()['worker_available'], 'no')
        self.inbox.write_text('not a directory')
        self.assertEqual(self.status_data()['worker_available'], 'no')

    def test_stale_health_matches_initial_and_polled_labels_without_erasing_history(self):
        self.publish(dsm_checked_epoch=str(int(time.time()) - 3600), dsm_match='yes', dsm_default='true',
                     state='running', last_verified='2026-09-30 03:08:58', last_run='2026-09-30 03:08:58',
                     message='Renewal check complete; valid certificate verified in DSM')
        data = self.status_data()
        self.assertEqual(data['dsm_freshness'], 'stale')
        self.assertEqual((data['dsm_match'], data['dsm_default_raw']), ('unknown', 'unknown'))
        expected = dict(dsmMatch='Status needs refresh', dsmDefault='Status needs refresh',
                        dsmDefaultState='Status needs refresh', lastVerified='2026-09-30 03:08:58',
                        statusMessage='Renewal check complete; valid certificate verified in DSM')
        self.run_ui(self.ui_fixture(data, expectedInitialText=expected, expectedText=expected))

    def test_unverified_health_is_distinct_from_stale_health(self):
        data = self.status_data()
        self.assertEqual(data['dsm_freshness'], 'unverified')
        expected = dict(dsmMatch='Not yet verified', dsmDefault='Unknown', dsmDefaultState='Not yet determined')
        self.run_ui(self.ui_fixture(dict(data, state='running'), expectedInitialText=expected, expectedText=expected))

    def test_fresh_match_and_mismatch_preserve_initial_and_poll_meaning(self):
        for match, default, match_text, role in (
                ('yes', 'true', 'Verified — certificate matches', 'Default certificate'),
                ('no', 'false', 'Mismatch — certificate differs', 'Not the DSM default')):
            with self.subTest(match=match):
                self.publish(dsm_checked_epoch=str(int(time.time())), dsm_match=match, dsm_default=default)
                data = self.status_data()
                self.assertEqual(data['dsm_freshness'], 'fresh')
                expected = dict(dsmMatch=match_text, dsmDefault='Yes' if default == 'true' else 'No',
                                dsmDefaultState=role, statusFreshness='Live status updates automatically.')
                requests = self.run_ui(self.ui_fixture(data, expectedInitialText=expected, expectedText=expected))
                self.assertEqual(len(requests), 1, 'fresh status should not enqueue a redundant refresh')

    def test_past_deadline_is_suppressed_without_inventing_a_future_time(self):
        self.active()
        old = str(int(time.time()) - 3600)
        self.publish(next_auto_epoch=old, dsm_checked_epoch=str(int(time.time())), state='running')
        data = self.status_data()
        self.assertEqual((data['next_auto'], data['next_auto_stale'], data['next_auto_text']),
                         ('', 'yes', 'Status needs refresh'))
        self.assertEqual((self.status / 'next_auto_epoch').read_text(), old, 'CGI must not rewrite the timer cache')
        expected = dict(nextAuto='Status needs refresh')
        self.run_ui(self.ui_fixture(data, expectedInitialText=expected, expectedText=expected))
        # The poll renderer also rejects a past epoch if a malformed response fails to flag it.
        self.run_ui(self.ui_fixture(dict(data, next_auto=old, next_auto_stale='no'),
                                    expectedInitialText=expected, expectedText=expected))

    def test_server_clock_controls_future_deadline_despite_client_clock_skew(self):
        self.active()
        self.publish(dsm_checked_epoch=str(int(time.time())))
        data = self.status_data()
        self.run_ui(self.ui_fixture(data, browserEpoch=int(time.time()) + 86400,
                                    expectedInitialNextEpoch=EPOCH, expectedNextEpoch=EPOCH))

    def test_refresh_failure_is_visible_and_preserves_operation_history(self):
        self.active()
        self.publish(dsm_checked_epoch=str(int(time.time()) - 3600), next_auto_epoch=str(int(time.time()) - 3600),
                     dsm_match='yes', dsm_default='true', state='success', last_verified='2026-09-30 03:08:58',
                     message='Renewal check complete; valid certificate verified in DSM')
        data = self.status_data()
        requests = self.run_ui(self.ui_fixture(data, refreshFailure='Queue unavailable',
            expectedText=dict(statusFreshness='Status refresh failed: Queue unavailable. Check Automation and try Refresh status again.',
                              statusMessage=data['message'], lastVerified=data['last_verified'],
                              dsmMatch='Status needs refresh', nextAuto='Status needs refresh'),
            expectedDisabled=dict(statusRefreshBtn=False)))
        self.assertEqual([request['body']['action'] for request in requests if request['body']], ['refresh'])

    def test_refresh_pending_and_timeout_remain_visible_without_fabricated_deadline(self):
        self.active()
        self.publish(dsm_checked_epoch=str(int(time.time()) - 3600), next_auto_epoch=str(int(time.time()) - 3600),
                     dsm_match='yes', dsm_default='true', state='success')
        data = self.status_data()
        requests = self.run_ui(self.ui_fixture(data, statusPolls=[data, data],
            expectedText=dict(dsmMatch='Refreshing…', nextAuto='Refreshing…', statusRefreshBtn='Refreshing…'),
            expectedDisabled=dict(statusRefreshBtn=True), steps=[dict(advanceMs=91000, poll=True,
                expectedText=dict(statusFreshness='Status refresh has not completed. Check background processing in Automation, then try Refresh status again.',
                                  dsmMatch='Status needs refresh', nextAuto='Status needs refresh'),
                expectedDisabled=dict(statusRefreshBtn=False))]))
        self.assertEqual([request['body']['action'] for request in requests if request['body']], ['refresh'],
                         'timeout feedback should not immediately queue another automatic refresh')

    def test_same_second_refresh_completion_uses_its_job_receipt(self):
        self.active()
        self.publish(dsm_checked_epoch=str(int(time.time())), dsm_match='yes', dsm_default='true')
        data = self.status_data()
        job_id = 'offline-refresh-job'
        requests = self.run_ui(self.ui_fixture(data, statusPolls=[data, data], refreshJobId=job_id,
            jobReceipts=[dict(job_id=job_id, result='completed')], steps=[dict(refresh=True,
                expectedText=dict(dsmMatch='Verified — certificate matches', statusRefreshBtn='Refresh status',
                                  statusFreshness='Live status updates automatically.'),
                expectedDisabled=dict(statusRefreshBtn=False))]))
        self.assertEqual(sum('api=job' in request['url'] for request in requests), 1)
        self.assertEqual([request['body']['action'] for request in requests if request['body']], ['refresh'])

    def test_newer_metadata_does_not_finish_another_pending_refresh(self):
        self.publish(dsm_checked_epoch=str(int(time.time()) - 3600), state='success')
        stale = self.status_data()
        fresh = dict(stale, checked_epoch=str(int(time.time())), dsm_freshness='fresh', dsm_match='yes',
                     dsm_default='Yes', dsm_default_raw='true')
        job_id = 'offline-refresh-job'
        self.run_ui(self.ui_fixture(stale, statusPolls=[stale, fresh, fresh], refreshJobId=job_id,
            jobReceipts=[dict(job_id=job_id, result='queued'), dict(job_id=job_id, result='completed')],
            steps=[dict(poll=True, expectedText=dict(statusRefreshBtn='Refreshing…',
                           statusFreshness='Refreshing status… The last operation result remains above.'),
                        expectedDisabled=dict(statusRefreshBtn=True)),
                   dict(poll=True, expectedText=dict(statusRefreshBtn='Refresh status',
                           statusFreshness='Live status updates automatically.'),
                        expectedDisabled=dict(statusRefreshBtn=False))]))

    def test_failed_and_interrupted_refresh_receipts_stop_the_spinner(self):
        self.publish(dsm_checked_epoch=str(int(time.time()) - 3600), state='success')
        data = self.status_data()
        for result in ('failed', 'interrupted'):
            with self.subTest(result=result):
                job_id = 'offline-refresh-job'
                self.run_ui(self.ui_fixture(data, statusPolls=[data, data], refreshJobId=job_id,
                    jobReceipts=[dict(job_id=job_id, result=result)], steps=[dict(poll=True,
                        expectedText=dict(statusRefreshBtn='Refresh status', dsmMatch='Status needs refresh',
                            statusFreshness='Status refresh failed. Check Logs and background processing in Automation, then try Refresh status again.'),
                        expectedDisabled=dict(statusRefreshBtn=False))]))

    def test_status_poll_failure_has_visible_connection_feedback(self):
        self.run_ui(self.ui_fixture(statusPolls=[dict(fetchError='Connection unavailable')],
            expectedText=dict(statusFreshness='Cannot update status. Check your DSM session or connection, then try Refresh status again.'),
            expectedDisabled=dict(statusRefreshBtn=False)))

    def test_top_navigation_preserves_page_and_compact_toggle_state(self):
        self.run_ui(self.ui_fixture(navigation=dict(initialPage='dashboard', page='settings')))

    def test_top_navigation_preserves_saved_page_without_legacy_menu_state(self):
        self.run_ui(self.ui_fixture(storage={'sadleracme.tab': 'uninstall', 'sadleracme.menu-collapsed': 'true'},
                                    navigation=dict(initialPage='uninstall', page='backup')))

    def test_compact_navigation_closes_after_page_choice(self):
        self.run_ui(self.ui_fixture(windowWidth=700, navigation=dict(initialPage='dashboard', page='settings', compactPage='automation')))

    def test_top_navigation_works_when_session_storage_is_disabled(self):
        self.run_ui(self.ui_fixture(storageDisabled=True, navigation=dict(initialPage='dashboard', page='automation')))

    @unittest.skipUnless(os.geteuid() == 0, 'unprivileged CGI fixture needs root to change test UID')
    def test_worker_available_checks_actual_cgi_write_access(self):
        self.status_data()  # Create the CSRF token and settings lock first.
        self.root.chmod(0o755)
        self.etc.chmod(0o777)
        for path in self.etc.iterdir():
            path.chmod(0o666)
        for mode, expected in ((0o555, 'no'), (0o777, 'yes')):
            with self.subTest(mode=oct(mode)):
                self.inbox.chmod(mode)
                try:
                    result = subprocess.run(['sh', str(self.cgi)], capture_output=True, text=True,
                        env=dict(self.env, REQUEST_METHOD='GET', QUERY_STRING='api=status'),
                        user=65534, timeout=15)
                except OSError as error:
                    if error.errno in (errno.EINVAL, errno.EPERM):
                        self.skipTest('execution sandbox cannot switch to an unprivileged UID')
                    raise
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                data = json.loads(result.stdout.split('\n\n', 1)[1])
                self.assertEqual(data['package_running'], 'yes')
                self.assertEqual(data['worker_available'], expected)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(RenewalLabel(name) for name in sorted(RenewalLabel.__dict__)
                              if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
