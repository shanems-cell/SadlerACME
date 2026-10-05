#!/usr/bin/env python3
"""Check current public text, generated installed help and documentation assets.

Native screenshots may retain captured older versions. This checks written text
and embedded image identities, and never contacts DSM or certificate services.
"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version="([^"]+)"', (ROOT/'pkg/INFO').read_text(), re.M).group(1)
OLD_VERSION = re.compile(r'(?<!\d)0\.2\.\d+(?:[-_]\d+)?')
checks = []

def check(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)

public = list(ROOT.glob('*.md'))
check(bool(public), 'Public Markdown present')
for path in sorted(public):
    text = path.read_text(encoding='utf-8')
    check(not OLD_VERSION.search(text), f'{path.name}: no old SadlerACME version labels')
    check(text.count('```') % 2 == 0, f'{path.name}: balanced code fences')
    for target in re.findall(r'\]\(([^)]+)\)', text):
        parsed = urlsplit(target)
        if not parsed.scheme and parsed.path:
            local = (path.parent/unquote(parsed.path)).resolve()
            check(local.is_relative_to(ROOT) and local.exists(), f'{path.name}: link {target}')

check(VERSION not in (ROOT/'QUICKSTART.md').read_text(), 'QuickStart remains release-version-independent')
check(VERSION not in (ROOT/'README.md').read_text(), 'README remains release-version-independent')

class HelpPage(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.visible = []; self.script = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('style','script'): self.script += 1
        if tag == 'a':
            value = dict(attrs).get('href')
            if value: self.links.append(value)
    def handle_endtag(self, tag):
        if tag in ('style','script'): self.script -= 1
    def handle_data(self, data):
        if not self.script: self.visible.append(data)

help_dir = ROOT/'.build/payload/ui'
with tempfile.TemporaryDirectory(prefix='sadler-docs-') as tmp:
    subprocess.run([sys.executable, str(ROOT/'tools/build_help.py'), str(ROOT), tmp], check=True)
    for name in ('QUICKSTART','WORKFLOW','RECOVERY'):
        path = help_dir/(name+'.html')
        html = path.read_text(encoding='utf-8')
        check(path.read_bytes() == (Path(tmp)/path.name).read_bytes(), f'{name}: generated directly from current source')
        parsed = HelpPage(); parsed.feed(html)
        text = ' '.join(parsed.visible)
        check(VERSION in text and 'Public Beta' in text, f'{name}: current release banner')
        check(not OLD_VERSION.search(text), f'{name}: no old version in visible text')
        check('Development/test build' not in text, f'{name}: no old development banner')
        for link in parsed.links:
            url = urlsplit(link)
            if not url.scheme and url.path:
                check((help_dir/unquote(url.path)).is_file(), f'{name}: installed link {link}')
        check('sadleracme-emergency-remove.txt' in parsed.links, f'{name}: installed helper link')

manifest=json.loads((ROOT/'docs/screenshot-manifest.json').read_text())
images=manifest['images']
check(len(images)==11, 'Eleven selected original screenshots')
for image in images:
    data=(ROOT/'docs/images'/image['file']).read_bytes()
    check(hashlib.sha256(data).hexdigest()==image['sha256'], f'{image["file"]}: original identity')

guide=ROOT/'docs/Installation-and-Interface-Guide.docx'
with zipfile.ZipFile(guide) as z:
    text=[]
    for name in z.namelist():
        if name.endswith('.xml') and (name.startswith('word/') or name.startswith('docProps/')):
            root=ET.fromstring(z.read(name)); text.extend(root.itertext())
    check(not OLD_VERSION.search(' '.join(text)), 'Illustrated guide: no old version in written XML text')
    check('Screenshots retain the version numbers' in ' '.join(text), 'Guide explains captured-version screenshots')
    embedded={hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}
    check(embedded=={x['sha256'] for x in images}, 'Guide embeds all eleven original selected screenshots exactly')

report={'version':VERSION,'passed':True,'checks':checks,
        'scope':'Current written documents, generated help, local links and asset identity; screenshot pixels may show earlier captured versions. No native DSM test.'}
(ROOT/'tests'/f'RESULTS-{VERSION}-documentation.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'{len(checks)} documentation checks passed.')
