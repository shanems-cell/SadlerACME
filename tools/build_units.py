"""Expand trusted unit templates. Hash the COPY, never check then execute target."""
from pathlib import Path
import hashlib, sys, json
build = Path(sys.argv[1])
assert (build / 'payload/bin/sadleracme-root').stat().st_size < 524288
digest = hashlib.sha256((build / 'payload/bin/sadleracme-root').read_bytes()).hexdigest()
for unit in (build / 'spk/conf/systemd').glob('*.service'):
    text = unit.read_text()
    marker = next(line for line in text.splitlines() if line.startswith('ExecStart='))
    action = marker.rsplit(' ', 1)[1]
    assert action in ('worker', 'scheduled', 'systemd-bootstrap', 'systemd-setup', 'setup-expired', 'expire-transfers')
    command = ('umask 077; PATH=/usr/syno/bin:/usr/syno/sbin:/usr/bin:/bin:/usr/sbin:/sbin; export PATH; '
               'd=$(mktemp -d /run/sadleracme.XXXXXXXX) || exit 1; '
               "trap 'rm -rf \"$d\"' EXIT; "
               'head -c 524288 /var/packages/sadleracme/target/bin/sadleracme-root > "$d/worker" || exit 1; '
               'chmod 0400 "$d/worker" || exit 1; '
               f'echo "{digest}  $d/worker" | sha256sum -c - >/dev/null || exit 1; '
               f'/bin/sh "$d/worker" {action}')
    # systemd accepts JSON-compatible double-quoted string escapes here.
    # Double dollars prevent systemd environment substitution before sh runs.
    encoded = json.dumps(command.replace('$', '$$').replace('%', '%%'))
    unit.write_text(text.replace(marker, "ExecStart=/bin/sh -c " + encoded))
