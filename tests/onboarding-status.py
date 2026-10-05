#!/usr/bin/env python3
"""Pristine-setup read-only status hint from assembled CGI in the existing fixture."""
from pathlib import Path
import importlib.util,json,unittest
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fixture',R/'tests/regression.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class OnboardingStatus(unittest.TestCase):
    def setUp(self):
        self.f=m.Regression();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.config=dict(m.CONFIG,domains=[],cf_token='')
        self.save()
    def save(self):
        (self.f.etc/'settings.json').write_text(json.dumps(self.config))
    def status(self):
        return json.loads(self.f.request(query='api=status').split('\n\n',1)[1])
    def test_empty_hint_does_not_write_settings_or_queue(self):
        before=(self.f.etc/'settings.json').read_bytes()
        self.assertEqual(self.status()['setup_required'],'yes')
        self.assertEqual((self.f.etc/'settings.json').read_bytes(),before)
        self.assertFalse(list(self.f.inbox.glob('*.job')))
    def test_domains_make_configuration_nonpristine(self):
        self.config['domains']=['example.com'];self.save()
        self.assertEqual(self.status()['setup_required'],'no')
    def test_token_makes_configuration_nonpristine(self):
        self.config['cf_token']='fixture-token-not-live';self.save()
        data=self.status();self.assertEqual(data['setup_required'],'no')
        self.assertNotIn('fixture-token-not-live',json.dumps(data))
    def test_retained_certificate_makes_configuration_nonpristine(self):
        # CGI must use root-published metadata, not inspect private key storage.
        (self.f.status/'local_cert_available').write_text('yes')
        self.assertEqual(self.status()['setup_required'],'no')
    def test_previous_worker_makes_configuration_nonpristine(self):
        (self.f.status/'worker_last_seen').write_text('2026-10-04 10:00:00')
        self.assertEqual(self.status()['setup_required'],'no')
    def test_existing_failure_not_rewritten_by_cgi_hint(self):
        (self.f.status/'state').write_text('error')
        (self.f.status/'message').write_text('Synthetic permission failure')
        data=self.status();self.assertEqual(data['state'],'error');self.assertEqual(data['message'],'Synthetic permission failure')
    def test_stopped_package_not_reclassified_as_running(self):
        (self.f.var/'package.running').unlink()
        self.assertEqual(self.status()['package_running'],'no')
if __name__=='__main__':unittest.main(verbosity=2)
