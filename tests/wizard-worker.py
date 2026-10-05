#!/usr/bin/env python3
"""Offline wizard state/commit tests; no ACME, DNS or live DSM commands."""
import copy
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import unittest

spec = importlib.util.spec_from_file_location('sadler_regression', Path(__file__).with_name('regression.py'))
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)


class WizardWorker(regression.Regression):
    def setUp(self):
        super().setUp()
        self.original = copy.deepcopy(regression.CONFIG)
        self.draft = dict(regression.CONFIG, domains=['new.example.com'], cert_desc='Updated certificate')
        self.ca_key = regression.ec.generate_private_key(regression.ec.SECP384R1())
        self.clock = regression.datetime.datetime.now(regression.datetime.timezone.utc)
        self.ca_name = regression.x509.Name([regression.x509.NameAttribute(regression.NameOID.COMMON_NAME, 'Wizard test CA')])
        self.ca = (regression.x509.CertificateBuilder().subject_name(self.ca_name).issuer_name(self.ca_name)
                   .public_key(self.ca_key.public_key()).serial_number(regression.x509.random_serial_number())
                   .not_valid_before(self.clock - regression.datetime.timedelta(days=2))
                   .not_valid_after(self.clock + regression.datetime.timedelta(days=100))
                   .add_extension(regression.x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .sign(self.ca_key, regression.hashes.SHA384()))
        Path(self.env['SSL_CERT_FILE']).write_bytes(self.ca.public_bytes(regression.serialization.Encoding.PEM))
        self.old_generation = self.private / 'live-gen.original'
        self.certificate(self.old_generation, self.original['domains'])
        (self.private / 'live').symlink_to(self.old_generation.name)
        self.new_certificate = self.private / 'fixture-new'
        self.certificate(self.new_certificate, self.draft['domains'])
        self.archive = self.root / 'usr/syno/etc/certificate/_archive/existing'
        self.archive.mkdir(parents=True)
        for src, dst in [('key.pem', 'privkey.pem'), ('cert.pem', 'cert.pem'), ('ca.pem', 'chain.pem'), ('fullchain.pem', 'fullchain.pem')]:
            shutil.copy(self.old_generation / src, self.archive / dst)
        (self.private / 'dsm-id').write_text('existing')
        self.set_list([dict(id='existing', desc=self.original['cert_desc'], is_default=True)])
        self.shell('load_config\nadopt_legacy_profile\ncp "$CONFIG" "$ROOT_STATE/applied-settings.json"')
        self.saved_bytes = (self.etc / 'settings.json').read_bytes()
        self.old_signature = (self.private / 'applied_signature').read_bytes()
        self.old_pem = (self.private / 'live/cert.pem').read_bytes()
        self.prepare_job(self.draft)
        self.acme_boundary = '''
ensure_engine() { :; }
register_account() { mkdir -p "$1" "$2"; printf 'registered\\n' > "$1/account.conf"; }
issue_cert() {
  printf 'issued\\n' >> "$ROOT_STATE/issue-count"
  mkdir -p "$WORK/candidate"
  for pem in key.pem cert.pem ca.pem fullchain.pem; do cp "$ROOT_STATE/fixture-new/$pem" "$WORK/candidate/$pem"; done
  [ "$ECC" = 1 ] && fixture_profile="$2/${PRIMARY}_ecc" || fixture_profile="$2/$PRIMARY"
  mkdir -p "$fixture_profile"
  cp "$WORK/candidate/key.pem" "$fixture_profile/$PRIMARY.key"
  cp "$WORK/candidate/cert.pem" "$fixture_profile/$PRIMARY.cer"
  cp "$WORK/candidate/ca.pem" "$fixture_profile/ca.cer"
  cp "$WORK/candidate/fullchain.pem" "$fixture_profile/fullchain.cer"
  printf "Le_Domain='%s'\\n" "$PRIMARY" > "$fixture_profile/$PRIMARY.conf"
  ISSUE_RC=0
}
'''

    def certificate(self, destination, domains):
        destination.mkdir(parents=True)
        key = regression.ec.generate_private_key(regression.ec.SECP384R1())
        cert = (regression.x509.CertificateBuilder()
                .subject_name(regression.x509.Name([regression.x509.NameAttribute(regression.NameOID.COMMON_NAME, domains[0])]))
                .issuer_name(self.ca_name).public_key(key.public_key()).serial_number(regression.x509.random_serial_number())
                .not_valid_before(self.clock - regression.datetime.timedelta(days=1))
                .not_valid_after(self.clock + regression.datetime.timedelta(days=60))
                .add_extension(regression.x509.SubjectAlternativeName([regression.x509.DNSName(domain) for domain in domains]), critical=False)
                .sign(self.ca_key, regression.hashes.SHA384()))
        (destination / 'key.pem').write_bytes(key.private_bytes(regression.serialization.Encoding.PEM, regression.serialization.PrivateFormat.TraditionalOpenSSL, regression.serialization.NoEncryption()))
        (destination / 'cert.pem').write_bytes(cert.public_bytes(regression.serialization.Encoding.PEM))
        (destination / 'ca.pem').write_bytes(self.ca.public_bytes(regression.serialization.Encoding.PEM))
        (destination / 'fullchain.pem').write_bytes((destination / 'cert.pem').read_bytes() + (destination / 'ca.pem').read_bytes())

    def prepare_job(self, config, expected_hash=None):
        (self.private / 'work/config.json').write_text(json.dumps(config))
        if expected_hash is None:
            saved = json.loads((self.etc / 'settings.json').read_text())
            expected_hash = hashlib.sha256((json.dumps(saved, sort_keys=True, separators=(',', ':')) + '\n').encode()).hexdigest()
        (self.private / 'work/job.json').write_text(json.dumps(dict(action='wizard-apply', config=config, expected_settings_hash=expected_hash)))

    def apply(self, extra='', expected=0):
        return self.shell(self.acme_boundary + '\n' + extra + '\nrun_wizard_apply', expected=expected)

    def issue_count(self):
        p = self.private / 'issue-count'
        return len(p.read_text().splitlines()) if p.exists() else 0

    def test_staging_uses_draft_without_saved_settings_or_production_changes(self):
        self.shell(self.acme_boundary + '\nrun_wizard_test')
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertEqual((self.private / 'live/cert.pem').read_bytes(), self.old_pem)
        self.assertEqual((self.private / 'applied_signature').read_bytes(), self.old_signature)
        self.assertFalse((self.private / 'prod-certs/new.example.com_ecc').exists())
        self.assertTrue((self.private / 'stage-certs/new.example.com_ecc/new.example.com.cer').exists())
        self.assertEqual((self.archive / 'cert.pem').read_bytes(), self.old_pem)

    def test_successful_apply_commits_only_after_real_dsm_deployment(self):
        self.apply()
        settings = json.loads((self.etc / 'settings.json').read_text())
        self.assertEqual(settings['domains'], self.draft['domains'])
        self.assertEqual(settings['auto_renew'], '0')
        self.assertEqual((self.archive / 'cert.pem').read_bytes(), (self.new_certificate / 'cert.pem').read_bytes())
        self.assertEqual(self.issue_count(), 1)
        self.assertFalse((self.private / 'wizard-transaction').exists())
        self.assertFalse((self.private / 'wizard-apply.pending').exists())
        self.assertEqual((self.status / 'wizard_apply_pending').read_text().strip(), 'no')

    def test_unchanged_dsm_failure_restores_active_state_and_retry_reuses_issue(self):
        self.apply(extra='deploy_dsm() { fail "Synthetic failure before DSM write" deploy; }', expected=1)
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertEqual((self.private / 'live/cert.pem').read_bytes(), self.old_pem)
        self.assertEqual((self.private / 'applied_signature').read_bytes(), self.old_signature)
        self.assertEqual((self.archive / 'cert.pem').read_bytes(), self.old_pem)
        self.assertFalse((self.private / 'wizard-apply.pending').exists())
        self.assertTrue((self.private / 'wizard-retry/live/cert.pem').exists())
        self.assertEqual(self.issue_count(), 1)
        self.prepare_job(self.draft)
        self.apply()
        self.assertEqual(self.issue_count(), 1)
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['domains'], self.draft['domains'])

    def test_changed_dsm_failure_preserves_saved_settings_and_pauses_renewal(self):
        self.apply(extra=f'''deploy_dsm() {{
  cp "$LIVE/cert.pem" "{self.archive}/cert.pem"
  fail "Synthetic failure after DSM write" deploy
}}''', expected=1)
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertTrue((self.private / 'wizard-apply.pending').exists())
        self.assertTrue((self.private / 'wizard-transaction').exists())
        self.assertEqual((self.status / 'wizard_apply_pending').read_text().strip(), 'yes')
        self.assertIn('paused', (self.status / 'message').read_text())
        self.assertEqual((self.private / 'live/cert.pem').read_bytes(), (self.new_certificate / 'cert.pem').read_bytes())
        # A second failure cannot treat the uncertain prior deployment as an
        # ordinary unchanged baseline and inadvertently resume old settings.
        self.prepare_job(self.draft)
        self.apply(extra='deploy_dsm() { fail "Second failure" deploy; }', expected=1)
        self.assertTrue((self.private / 'wizard-apply.pending').exists())
        self.assertEqual(self.issue_count(), 1)

    def test_failed_settings_commit_leaves_explicit_pending_then_reuses_certificate(self):
        self.apply(extra='commit_settings_from_file() { return 1; }', expected=1)
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertTrue((self.private / 'wizard-transaction/deployed').exists())
        self.assertTrue((self.private / 'wizard-apply.pending').exists())
        self.assertIn('saving settings failed', (self.status / 'message').read_text())
        self.prepare_job(self.draft)
        self.apply()
        self.assertEqual(self.issue_count(), 1)
        self.assertFalse((self.private / 'wizard-apply.pending').exists())

    def test_stale_saved_settings_reference_fails_before_issuance(self):
        self.prepare_job(self.draft, expected_hash='0' * 64)
        self.apply(expected=1)
        self.assertEqual(self.issue_count(), 0)
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertFalse((self.private / 'wizard-transaction').exists())

    def test_configuration_lock_blocks_direct_settings_save(self):
        self.csrf()
        lock = self.status / 'configuration.lock'
        lock.touch()
        with lock.open('r') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            response = self.request(dict(action='save', csrf=self.csrf(), email='admin@example.com', domains='other.example.com', key_type='ec-384', cert_desc='Changed', cf_token=''))
        self.assertIn('configuration operation is running', response)
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)

    def test_crash_after_new_live_before_signature_retains_candidate(self):
        self.apply(extra='''install_live_files() {
  generation=$(mktemp -d "$ROOT_STATE/live-gen.XXXXXXXX")
  cp "$WORK/candidate/"*.pem "$generation/"
  rm -f "$LIVE"
  ln -s "${generation##*/}" "$LIVE"
  exit 31
}''', expected=1)
        self.assertEqual((self.private / 'live/cert.pem').read_bytes(), self.old_pem)
        self.assertTrue((self.private / 'wizard-retry/live/cert.pem').exists())
        self.prepare_job(self.draft)
        self.apply()
        self.assertEqual(self.issue_count(), 1)

    def test_crash_before_live_publication_retains_valid_issued_profile(self):
        self.apply(extra='install_live_files() { exit 32; }', expected=1)
        self.assertEqual((self.private / 'live/cert.pem').read_bytes(), self.old_pem)
        self.assertTrue((self.private / 'wizard-retry/live/cert.pem').exists())
        self.prepare_job(self.draft)
        self.apply()
        self.assertEqual(self.issue_count(), 1)

    def test_completed_settings_commit_recovers_after_marker_interruption(self):
        self.apply(extra='''workflow_apply_completed() { exit 33; }''', expected=33)
        self.assertTrue((self.private / 'wizard-transaction/committed').exists())
        self.shell('configuration_lock\nworkflow_recover_pending\nconfiguration_unlock')
        self.assertFalse((self.private / 'wizard-transaction').exists())
        self.assertFalse((self.private / 'wizard-apply.pending').exists())
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['domains'], self.draft['domains'])

    def test_job_receipt_rejects_paths_and_supports_interrupted(self):
        self.shell('ACTIVE_JOB="../escape.job"\nworkflow_job_receipt 1', expected=1)
        self.assertFalse((self.status / 'escape.job.json').exists())
        self.shell('ACTIVE_JOB=abc123-456.job\nworkflow_job_receipt 1 interrupted')
        receipt = json.loads((self.status / 'jobs/abc123-456.job.json').read_text())
        self.assertEqual(receipt['result'], 'interrupted')

    def test_pending_wizard_blocks_restore_before_any_mutation(self):
        (self.private / 'wizard-apply.pending').touch()
        self.shell('''restore_backup() { : > "$ROOT_STATE/UNEXPECTED-RESTORE"; }
run_restore''', expected=1)
        self.assertFalse((self.private / 'UNEXPECTED-RESTORE').exists())
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertIn('before restoring a backup', (self.status / 'message').read_text())

    def test_next_worker_recovers_interrupted_apply_before_refresh(self):
        self.apply(extra='''deploy_dsm() { fail "Interrupted before deployment" deploy; }
workflow_recover_pending() { return 0; }''', expected=1)
        self.assertTrue((self.private / 'wizard-transaction/started').exists())
        self.assertTrue((self.private / 'wizard-apply.pending').exists())
        result = self.full_worker('refresh')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.etc / 'settings.json').read_bytes(), self.saved_bytes)
        self.assertEqual((self.private / 'live/cert.pem').read_bytes(), self.old_pem)
        self.assertEqual((self.private / 'applied_signature').read_bytes(), self.old_signature)
        self.assertFalse((self.private / 'wizard-apply.pending').exists())
        self.assertTrue((self.private / 'wizard-retry/live/cert.pem').exists())

    def test_pending_apply_blocks_scheduled_and_manual_renewal(self):
        (self.private / 'wizard-apply.pending').touch()
        self.shell(self.acme_boundary + '\nscheduled')
        self.assertEqual(self.issue_count(), 0)
        self.shell(self.acme_boundary + '\nrun_check', expected=1)
        self.assertEqual(self.issue_count(), 0)
        self.assertIn('recovery is pending', (self.status / 'message').read_text())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(WizardWorker(name) for name in sorted(WizardWorker.__dict__) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
