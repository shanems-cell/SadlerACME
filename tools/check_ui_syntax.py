#!/usr/bin/env python3
"""Syntax and metadata checks for the built UI candidate; no runtime execution."""
from pathlib import Path
import ast,importlib.util,json,py_compile,re,subprocess,tempfile
R=Path(__file__).resolve().parents[1];checks=[]
def command(kind,p,args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=20)
    checks.append(dict(kind=kind,file=str(p.relative_to(R)) if p.is_relative_to(R) else p.name,passed=result.returncode==0,detail=result.stderr.strip()))
    if result.returncode:raise AssertionError(result.stderr)
for p in sorted((R/'src/ui').glob('*.js')):command('JavaScript',p,['node','--check',str(p)])
for parent in [R/'src',R/'pkg/scripts',R/'.build/payload/bin']:
    for p in sorted(parent.rglob('*')):
        if not p.is_file():continue
        if p.suffix=='.sh' or p.name=='index.cgi' or p.read_bytes()[:24].startswith((b'#!/bin/sh',b'#!/bin/bash')):
            command('shell',p,['sh','-n',str(p)])
command('assembled CGI',R/'.build/payload/ui/index.cgi',['sh','-n',str(R/'.build/payload/ui/index.cgi')])
for p in [R/'src/ui/config',R/'pkg/conf/privilege',R/'pkg/conf/resource']:
    json.loads(p.read_text());checks.append(dict(kind='JSON',file=str(p.relative_to(R)),passed=True))
for parent in [R/'tools',R/'tests']:
    for p in sorted(parent.glob('*.py')):
        ast.parse(p.read_text());checks.append(dict(kind='Python AST',file=str(p.relative_to(R)),passed=True))
# Script after shell expansion: real fixture, not raw CGI shell placeholders.
spec=importlib.util.spec_from_file_location('fixture',R/'tests/regression.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
f=m.Regression();f.setUp()
try:
    html=f.request()
    for i,s in enumerate(re.findall(r'<script>(.*?)</script>',html,re.S)):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/f'rendered-inline-{i}.js';p.write_text(s);command('rendered JavaScript',p,['node','--check',str(p)])
finally:f.doCleanups()
info=(R/'pkg/INFO').read_text();version=re.search(r'^version="([^"]+)"',info,re.M).group(1)
assert version=='1.0.0-1'
assert f'VERSION="{version}"' in (R/'src/ui/index.cgi').read_text()
# PNG asset integrity, with no raster generation or font redistribution.
from PIL import Image
for p in sorted((R/'src/ui/images').glob('*.png'))+list((R/'pkg').glob('PACKAGE_ICON*.PNG')):
    with Image.open(p) as image:image.verify()
    checks.append(dict(kind='PNG',file=str(p.relative_to(R)),passed=True))
(R/'tests/RESULTS-1.0.0-1-syntax.json').write_text(json.dumps(dict(version=version,passed=True,checks=checks),indent=2)+'\n')
print(f'{len(checks)} syntax/configuration/asset checks passed; versions agree.')
