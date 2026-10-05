#!/usr/bin/env python3
"""Offline email-boundary checks; no untrusted email reaches real acme.sh.

The synthetic DSM fixture redirects all state to a temporary directory. ACME
is replaced with an inert call marker, never the upstream configuration writer.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

spec = importlib.util.spec_from_file_location('email_regression', Path(__file__).with_name('regression.py'))
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)

UNSAFE_EMAILS = (
    "admin';UNTRUSTED_TEXT;#@example.com",
    'admin`UNTRUSTED_TEXT`@example.com',
    'admin$(UNTRUSTED_TEXT)@example.com',
    'admin;UNTRUSTED_TEXT@example.com',
    'admin\\unsafe@example.com',
    'admin@example.com\nUNTRUSTED_TEXT',
    'UNTRUSTED_TEXT\nadmin@example.com',
    'administrátor@example.com',
)
SAFE_EMAIL = 'Admin.Name_1+renewal%tag@example-domain.co.uk'


class EmailSecurity(regression.Regression):
    def json_request(self, payload):
        body = json.dumps(payload)
        env = dict(self.env, REQUEST_METHOD='POST', CONTENT_TYPE='application/json',
                   CONTENT_LENGTH=str(len(body.encode())), QUERY_STRING='')
        result = subprocess.run(['sh', str(self.cgi)], input=body, text=True,
                                capture_output=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return result.stdout

    def form(self, email):
        return dict(action='save', csrf=self.csrf(), email=email,
                    domains='\n'.join(regression.CONFIG['domains']), key_type='ec-384',
                    cert_desc='Email validation fixture', cf_token=regression.TOKEN,
                    default_on_create='0', auto_renew='0', dns_sleep='30')

    def backup(self, email):
        settings = {key: value for key, value in regression.CONFIG.items() if key != 'cf_token'}
        settings.update(email=email, auto_renew='0')
        return dict(format='SadlerACME', version=1, created_at='2026-09-27T00:00:00Z',
                    settings=settings, certificate=None, acme_account_key=None,
                    metadata=dict(domains=settings['domains'], key_type=settings['key_type']))

    def test_root_rejects_shell_characters_before_acme_or_snapshot(self):
        protected_snapshot = self.private / 'last-settings.json'
        protected_snapshot.write_text('original protected settings\n')
        for email in (*UNSAFE_EMAILS, 'admin@example.com\n'):
            with self.subTest(email=email):
                (self.private / 'work/config.json').write_text(json.dumps(dict(regression.CONFIG, email=email)))
                self.shell('''
ensure_engine() { :; }
acme_invoke() { : > "$ROOT_STATE/acme-invoked"; return 91; }
run_test
''', expected=1)
                self.assertFalse((self.private / 'acme-invoked').exists())
                self.assertEqual(protected_snapshot.read_text(), 'original protected settings\n')
                self.assertIn('Invalid or incomplete configuration', (self.status / 'message').read_text())

    def test_legacy_cgi_rejects_unsafe_email_without_saving(self):
        original = (self.etc / 'settings.json').read_bytes()
        for email in UNSAFE_EMAILS:
            with self.subTest(email=email):
                response = self.request(self.form(email))
                self.assertIn('Email address is not valid', response)
                self.assertEqual((self.etc / 'settings.json').read_bytes(), original)

    def test_json_wizard_rejects_unsafe_email_without_queueing(self):
        csrf = self.csrf()
        for email in (*UNSAFE_EMAILS, 'admin@example.com\n'):
            with self.subTest(email=email):
                response = self.json_request(dict(action='wizard-test', csrf=csrf,
                                                 config=dict(regression.CONFIG, email=email)))
                self.assertIn('400 Bad Request', response)
                self.assertFalse(json.loads(response.split('\n\n', 1)[1])['ok'])
                self.assertEqual(list(self.inbox.glob('*.job')), [])

    def test_recovery_rejects_unsafe_email_before_state_mutation(self):
        (self.private / 'prod-config').mkdir()
        (self.private / 'prod-config/account.conf').write_text('existing account data\n')
        (self.private / 'applied_signature').write_text('original-signature\n')
        original = (self.etc / 'settings.json').read_bytes()
        for email in (*UNSAFE_EMAILS, 'admin@example.com\n'):
            with self.subTest(email=email):
                job = dict(config=regression.CONFIG, backup=self.backup(email))
                (self.private / 'work/job.json').write_text(json.dumps(job))
                self.shell('''
acme_invoke() { : > "$ROOT_STATE/acme-invoked"; return 91; }
restore_backup
''', expected=1)
                self.assertEqual((self.etc / 'settings.json').read_bytes(), original)
                self.assertEqual((self.private / 'prod-config/account.conf').read_text(), 'existing account data\n')
                self.assertEqual((self.private / 'applied_signature').read_text(), 'original-signature\n')
                self.assertFalse((self.private / 'recovery-transaction').exists())
                self.assertFalse((self.private / 'acme-invoked').exists())
                self.assertIn('Recovery backup format', (self.status / 'message').read_text())

    def test_common_plus_address_passes_all_four_boundaries(self):
        (self.private / 'work/config.json').write_text(json.dumps(dict(regression.CONFIG, email=SAFE_EMAIL)))
        self.shell('''
acme_invoke() { printf '%s' "$EMAIL" > "$ROOT_STATE/acme-invoked"; return 0; }
load_config
register_account "$PROD_CFG" "$PROD_CERTS" "$LE_PROD"
''')
        self.assertEqual((self.private / 'acme-invoked').read_text(), SAFE_EMAIL)
        self.assertIn('Settings saved', self.request(self.form(SAFE_EMAIL)))
        self.assertEqual(json.loads((self.etc / 'settings.json').read_text())['email'], SAFE_EMAIL)
        response = self.json_request(dict(action='wizard-test', csrf=self.csrf(),
                                         config=dict(regression.CONFIG, email=SAFE_EMAIL)))
        self.assertTrue(json.loads(response.split('\n\n', 1)[1])['ok'])
        self.assertEqual(len(list(self.inbox.glob('*.job'))), 1)
        (self.private / 'work/recovery.json').write_text(json.dumps(self.backup(SAFE_EMAIL)))
        self.shell('recovery_validate_document "$WORK/recovery.json"')

    def test_untouched_recovery_settings_still_allow_empty_email(self):
        backup = copy.deepcopy(self.backup(''))
        backup['settings']['domains'] = []
        backup['metadata']['domains'] = []
        (self.private / 'work/recovery.json').write_text(json.dumps(backup))
        self.shell('recovery_validate_document "$WORK/recovery.json"')


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(EmailSecurity(name) for name in sorted(EmailSecurity.__dict__)
                              if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
