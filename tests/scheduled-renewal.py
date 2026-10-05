#!/usr/bin/env python3
"""Supplemental offline checks for the complete scheduled renewal entry path.

Uses the existing temporary DSM fixtures and the generated service launcher.
Only the external acme.sh invocation is replaced with a local issuer boundary;
DSM command mocks come from the existing fixtures. Worker initialisation,
locking, configuration guards, certificate validation, live-file publication,
DSM-file replacement, recovery journals, status, and history remain real.

The issuer boundary requires a deliberately overdue fixture profile. This does
not test acme.sh's real due decision, internet/DNS/CA behavior, systemd timer
firing, NAS service reloads, or the NAS trust store. No host clock is changed.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
import regression as fixtures


class ScheduledRenewal(fixtures.Regression):
    old_stamp = '2020-01-02 03:04:05'

    def setUp(self):
        super().setUp()
        # Model systemd's actual NEXT independently of worker start time. This
        # catches any return to estimating the display from last_auto_check.
        deadline = fixtures.datetime.datetime(2026, 9, 28, 19, 16, 27, tzinfo=fixtures.datetime.timezone.utc)
        self.next_check_epoch = int(deadline.timestamp())
        timer_row = deadline.strftime('%a %Y-%m-%d %H:%M:%S UTC') + ' 5h 59min left n/a n/a pkg-sadleracme-renew.timer pkg-sadleracme-renew.service'
        systemctl_base = self.bin / 'systemctl-base'
        (self.bin / 'systemctl').rename(systemctl_base)
        self.write_exe(self.bin / 'systemctl', '''#!/bin/sh
if [ "$1" = list-timers ]; then
  printf '%s\\n' ''' + shlex.quote(timer_row) + '''
  exit 0
fi
if [ "$1" = show ] && [ "$2" = pkg-sadleracme-renew.timer ]; then
  case "$*" in
    *--value*) printf 'active\\n';;
    *) printf 'LoadState=loaded\\nActiveState=active\\n';;
  esac
  exit 0
fi
exec ''' + shlex.quote(str(systemctl_base)) + ''' "$@"
''')
        # Both generations use one fixture CA. The base helper gives each
        # certificate a different key under the same issuer name, which is
        # ambiguous when both roots are in OpenSSL's temporary trust bundle.
        self.ca_key = fixtures.ec.generate_private_key(fixtures.ec.SECP384R1())
        self.ca_name = fixtures.x509.Name([fixtures.x509.NameAttribute(fixtures.NameOID.COMMON_NAME, 'Scheduled renewal fixture CA')])
        self.clock = fixtures.datetime.datetime.now(fixtures.datetime.timezone.utc)
        self.ca = (fixtures.x509.CertificateBuilder().subject_name(self.ca_name).issuer_name(self.ca_name)
                   .public_key(self.ca_key.public_key()).serial_number(fixtures.x509.random_serial_number())
                   .not_valid_before(self.clock - fixtures.datetime.timedelta(days=2))
                   .not_valid_after(self.clock + fixtures.datetime.timedelta(days=100))
                   .add_extension(fixtures.x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .sign(self.ca_key, fixtures.hashes.SHA384()))
        Path(self.env['SSL_CERT_FILE']).write_bytes(self.ca.public_bytes(fixtures.serialization.Encoding.PEM))
        self.issued = self.private / 'issuer-fixture'
        self.write_certificate(self.issued, 60)
        self.acme_calls = self.root / 'acme-calls.jsonl'
        self.reload_calls = self.root / 'reload-calls'
        self.network_attempt = self.root / 'network-attempt'
        self.write_exe(self.bin / 'curl', '#!/bin/sh\ntouch ' + shlex.quote(str(self.network_attempt)) + '\nexit 97\n')
        self.write_exe(self.root / 'usr/syno/bin/synow3tool',
                       '#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(self.reload_calls)) + '\n')
        share = self.base / 'target/share/acme.sh-3.1.5'
        shutil.copytree(fixtures.ROOT / 'vendor/acme.sh-3.1.5', share)
        issuer = self.root / 'issuer.py'
        issuer.write_text(f'''import json, os, re, shutil, sys, time
from pathlib import Path
args = sys.argv[1:]
with Path({str(self.acme_calls)!r}).open('a') as calls:
    calls.write(json.dumps(args) + '\\n')
def option(name):
    return args[args.index(name) + 1]
if '--register-account' in args:
    print('Offline account registration succeeded')
    raise SystemExit(0)
assert '--issue' in args, 'unexpected ACME operation'
assert '--force' not in args, 'scheduled renewal must not force issuance'
primary = option('-d')
destination = Path(option('--cert-home')) / (primary + '_ecc')
profile = (destination / (primary + '.conf')).read_text()
due = re.search(r"^Le_NextRenewTime='([0-9]+)'$", profile, re.M)
assert due and int(due.group(1)) < time.time(), 'fixture profile must be overdue'
source = Path({str(self.issued)!r})
rc = int(os.environ.get('TEST_ISSUE_RC', '0'))
if rc:
    # Model a failed issuer leaving partial new output beside older files.
    shutil.copyfile(source / 'cert.pem', destination / (primary + '.cer'))
    print('Offline issuer failed after leaving a partial certificate file')
    raise SystemExit(rc)
for source_name, target_name in [('key.pem', primary + '.key'), ('cert.pem', primary + '.cer'),
                                 ('ca.pem', 'ca.cer'), ('fullchain.pem', 'fullchain.cer')]:
    shutil.copyfile(source / source_name, destination / target_name)
print('Offline non-forced issuance succeeded')
''')
        # Inject the boundary only into the private test copy, before the real
        # entry dispatcher. The repository worker itself is never changed.
        boundary = '\nacme_invoke() { ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(issuer)) + ' "$@"; }\n\n'
        marker = '# All entry points share'
        worker = self.worker.read_text()
        self.assertEqual(worker.count(marker), 1)
        self.worker.write_text(worker.replace(marker, boundary + marker))

        build = self.root / 'unit-build'
        payload = build / 'payload/bin/sadleracme-root'
        payload.parent.mkdir(parents=True)
        shutil.copyfile(self.worker, payload)
        units = build / 'spk/conf/systemd'
        units.mkdir(parents=True)
        unit = units / 'pkg-sadleracme-renew.service'
        shutil.copyfile(fixtures.ROOT / 'pkg/conf/systemd/pkg-sadleracme-renew.service', unit)
        subprocess.run([sys.executable, str(fixtures.ROOT / 'tools/build_units.py'), str(build)], check=True, timeout=15)
        line = next(line for line in unit.read_text().splitlines() if line.startswith('ExecStart='))
        command = json.loads(line.removeprefix('ExecStart=/bin/sh -c ')).replace('$$', '$')
        self.launcher = command.replace('/var/packages/sadleracme/target/bin/sadleracme-root', str(payload)).replace('/run/sadleracme.', str(self.root / 'snapshot.'))

    def write_certificate(self, destination, valid_days):
        destination.mkdir(parents=True)
        key = fixtures.ec.generate_private_key(fixtures.ec.SECP384R1())
        cert = (fixtures.x509.CertificateBuilder()
                .subject_name(fixtures.x509.Name([fixtures.x509.NameAttribute(fixtures.NameOID.COMMON_NAME, 'example.com')]))
                .issuer_name(self.ca_name).public_key(key.public_key()).serial_number(fixtures.x509.random_serial_number())
                .not_valid_before(self.clock - fixtures.datetime.timedelta(days=1))
                .not_valid_after(self.clock + fixtures.datetime.timedelta(days=valid_days))
                .add_extension(fixtures.x509.SubjectAlternativeName([fixtures.x509.DNSName(domain) for domain in fixtures.CONFIG['domains']]), critical=False)
                .sign(self.ca_key, fixtures.hashes.SHA384()))
        (destination / 'key.pem').write_bytes(key.private_bytes(fixtures.serialization.Encoding.PEM, fixtures.serialization.PrivateFormat.TraditionalOpenSSL, fixtures.serialization.NoEncryption()))
        (destination / 'cert.pem').write_bytes(cert.public_bytes(fixtures.serialization.Encoding.PEM))
        (destination / 'ca.pem').write_bytes(self.ca.public_bytes(fixtures.serialization.Encoding.PEM))
        (destination / 'fullchain.pem').write_bytes((destination / 'cert.pem').read_bytes() + (destination / 'ca.pem').read_bytes())

    def prepare_applied_certificate(self):
        self.old_generation = self.private / 'live-gen.original'
        self.write_certificate(self.old_generation, 20)
        (self.private / 'live').symlink_to(self.old_generation.name)
        self.targets = [self.root / 'usr/syno/etc/certificate/_archive/abc',
                        self.root / 'usr/syno/etc/certificate/system/default']
        for target in self.targets:
            target.mkdir(parents=True)
            for source, destination in [('key.pem', 'privkey.pem'), ('cert.pem', 'cert.pem'),
                                        ('ca.pem', 'chain.pem'), ('fullchain.pem', 'fullchain.pem')]:
                shutil.copyfile(self.old_generation / source, target / destination)
        self.set_list([dict(id='abc', desc=fixtures.CONFIG['cert_desc'], is_default=True)])
        (self.private / 'deployment-history-v2').touch()
        for name in ('last_issue', 'last_renewal', 'last_deploy'):
            (self.status / name).write_text(self.old_stamp + '\n')
        self.shell('load_config\nadopt_legacy_profile')
        profile = self.private / 'prod-certs/example.com_ecc/example.com.conf'
        due = re.search(r"^Le_NextRenewTime='([0-9]+)'$", profile.read_text(), re.M)
        self.assertIsNotNone(due)
        self.assertLess(int(due.group(1)), time.time())
        self.previous_files = {path: path.read_bytes() for folder in [self.old_generation, *self.targets] for path in folder.iterdir()}

    def run_scheduled(self, expected=0, **env):
        before = int(time.time())
        result = subprocess.run(['sh', '-c', self.launcher], capture_output=True, text=True,
                                env=dict(self.env, **env), timeout=15)
        after = int(time.time())
        self.assertEqual(result.returncode, expected, result.stderr + '\n' + result.stdout)
        self.assertFalse(self.network_attempt.exists())
        self.assertFalse(list(self.root.glob('snapshot.*')))
        self.assertFalse(list(self.private.glob('work.*')))
        checked = int((self.private / 'last_auto_check').read_text())
        self.assertGreaterEqual(checked, before)
        self.assertLessEqual(checked, after)
        self.assertEqual(int((self.status / 'next_auto_epoch').read_text()), self.next_check_epoch)
        return result

    def assert_nonforced_production_invocations(self):
        calls = [json.loads(line) for line in self.acme_calls.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertIn('--register-account', calls[0])
        issue = calls[1]
        self.assertIn('--issue', issue)
        self.assertNotIn('--force', issue)
        self.assertEqual(issue[issue.index('--server') + 1], 'https://acme-v02.api.letsencrypt.org/directory')
        self.assertEqual(issue[issue.index('--dns') + 1], 'dns_cf')
        self.assertEqual([issue[index + 1] for index, arg in enumerate(issue) if arg == '-d'], fixtures.CONFIG['domains'])
        self.assertNotIn(fixtures.TOKEN, '\n'.join(' '.join(call) for call in calls))

    def test_scheduled_due_issuance_deploys_and_records_renewal(self):
        self.prepare_applied_certificate()
        previous_link = os.readlink(self.private / 'live')
        self.run_scheduled()
        self.assert_nonforced_production_invocations()
        self.assertNotEqual(os.readlink(self.private / 'live'), previous_link)
        for source, destination in [('key.pem', 'privkey.pem'), ('cert.pem', 'cert.pem'),
                                    ('ca.pem', 'chain.pem'), ('fullchain.pem', 'fullchain.pem')]:
            self.assertEqual((self.private / 'live' / source).read_bytes(), (self.issued / source).read_bytes())
            for target in self.targets:
                self.assertEqual((target / destination).read_bytes(), (self.issued / source).read_bytes())
        self.assertEqual((self.status / 'state').read_text().strip(), 'success')
        self.assertEqual((self.status / 'last_action').read_text().strip(), 'check')
        self.assertEqual((self.status / 'dsm_match').read_text().strip(), 'yes')
        self.assertEqual((self.status / 'dsm_cert_id').read_text().strip(), 'abc')
        self.assertEqual((self.status / 'dsm_default').read_text().strip(), 'true')
        for name in ('last_renewal', 'last_deploy'):
            value = (self.status / name).read_text().strip()
            self.assertNotEqual(value, self.old_stamp)
            self.assertRegex(value, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertEqual((self.status / 'last_issue').read_text().strip(), self.old_stamp)
        self.assertEqual(self.reload_calls.read_text().splitlines(), ['--gen-all', '--nginx=reload'])
        for name in ('transaction.pending', 'reload.pending', 'deployment-history.pending'):
            self.assertFalse((self.private / name).exists())
        for path in self.old_generation.iterdir():
            self.assertEqual(path.read_bytes(), self.previous_files[path])

    def test_scheduled_issuance_failure_preserves_deployed_certificate_and_history(self):
        self.prepare_applied_certificate()
        previous_link = os.readlink(self.private / 'live')
        self.run_scheduled(expected=1, TEST_ISSUE_RC='1')
        self.assert_nonforced_production_invocations()
        self.assertEqual(os.readlink(self.private / 'live'), previous_link)
        self.assertEqual(self.previous_files, {path: path.read_bytes() for path in self.previous_files})
        for name in ('last_issue', 'last_renewal', 'last_deploy'):
            self.assertEqual((self.status / name).read_text().strip(), self.old_stamp)
        self.assertEqual((self.status / 'state').read_text().strip(), 'error')
        self.assertEqual((self.status / 'last_action').read_text().strip(), 'issue')
        self.assertIn('ACME issuance failed (exit 1)', (self.status / 'message').read_text())
        self.assertFalse(self.reload_calls.exists())

    def test_scheduled_before_first_apply_does_not_invoke_acme(self):
        self.run_scheduled()
        self.assertFalse(self.acme_calls.exists())
        self.assertFalse((self.private / 'live').exists())
        self.assertFalse(self.reload_calls.exists())
        self.assertEqual((self.status / 'state').read_text().strip(), 'idle')
        self.assertIn('No production certificate has been applied', (self.status / 'message').read_text())

    def test_scheduled_changed_configuration_requires_explicit_apply(self):
        self.prepare_applied_certificate()
        config = dict(fixtures.CONFIG, domains=['different.example.com'])
        (self.etc / 'settings.json').write_text(json.dumps(config))
        self.run_scheduled(expected=1)
        self.assertFalse(self.acme_calls.exists())
        self.assertFalse(self.reload_calls.exists())
        self.assertEqual(self.previous_files, {path: path.read_bytes() for path in self.previous_files})
        self.assertEqual((self.status / 'last_deploy').read_text().strip(), self.old_stamp)
        self.assertEqual((self.status / 'last_renewal').read_text().strip(), self.old_stamp)
        self.assertEqual((self.status / 'state').read_text().strip(), 'error')
        self.assertIn('Settings changed; use Issue / Apply', (self.status / 'message').read_text())


def load_tests(loader, tests, pattern):
    # Reuse the fixture helpers without rerunning the inherited base suite.
    return unittest.TestSuite(ScheduledRenewal(name) for name in ScheduledRenewal.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
