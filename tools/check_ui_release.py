#!/usr/bin/env python3
"""Verify a documentation-only release against its accepted installer.
Usage: python3 tools/check_ui_release.py /path/to/accepted-installer.spk
The baseline is external; this tool never contacts or changes a NAS.
"""
from pathlib import Path, PurePosixPath
import hashlib,io,json,re,sys,tarfile
R=Path(__file__).resolve().parents[1]
V=re.search(r'^version="([^"]+)"',(R/'pkg/INFO').read_text(),re.M).group(1)
BASE_HASH='26e6cc18e79279d9b000333dddac49f6999d2104c602d685ca2e90c54c6cbd50'
def sha(data): return hashlib.sha256(data).hexdigest()
def members(data):
    content={};meta={}
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            p=PurePosixPath(m.name)
            assert not p.is_absolute() and '..' not in p.parts,m.name
            assert m.name not in meta,('duplicate',m.name)
            assert m.isfile() or m.isdir(),('unexpected link/type',m.name)
            assert m.uid==0 and m.gid==0,('owner',m.name)
            assert not m.mode&0o022,('nonowner write',m.name)
            meta[m.name]={'mode':oct(m.mode),'size':m.size,'directory':m.isdir()}
            if m.isfile():content[m.name]=t.extractfile(m).read()
    return content,meta

def unpack(path):
    outer,om=members(path.read_bytes());payload,pm=members(outer['package.tgz'])
    return outer,om,payload,pm

base=Path(sys.argv[1]);assert sha(base.read_bytes())==BASE_HASH,'Unrecognised accepted baseline'
spk=R/'dist'/f'SadlerACME-{V}.spk'
a,am,b,bm=unpack(base);c,cm,d,dm=unpack(spk)
assert set(a)==set(c),'Outer scope changed'
for key in a:
    if key not in ('INFO','package.tgz'):assert a[key]==c[key],('protected outer file changed',key)
assert set(b)==set(d),'Payload file scope changed'
expected={'ui/index.cgi','ui/QUICKSTART.html','ui/WORKFLOW.html','ui/RECOVERY.html'}
changed={k for k in d if b[k]!=d[k]}
assert changed==expected,('Unexpected payload change',changed^expected)
for k in bm:
    assert k in dm and bm[k]['mode']==dm[k]['mode'],('Payload mode changed',k)
for k in am:
    assert k in cm and am[k]['mode']==cm[k]['mode'],('Outer mode changed',k)
oldversion=re.search(rb'^version="([^"]+)"',a['INFO'],re.M).group(1)
normal=d['ui/index.cgi'].replace(b'VERSION="'+V.encode()+b'"',b'VERSION="'+oldversion+b'"')
old_note=b'Upgrading from '+b'0.2.3'+b'-17? Choose <b>Update existing task</b> to replace its old command.'
new_note=b'Migrating an older task? Choose <b>Update existing task</b> to replace its old command.'
assert new_note in normal
normal=normal.replace(new_note,old_note)
assert normal==b['ui/index.cgi'],'CGI changed beyond the approved version and help sentence'
def metadata(data):return dict(re.findall(rb'^([a-z_]+)="([^"]*)"$',data,re.M))
ai,ci=metadata(a['INFO']),metadata(c['INFO'])
assert ci['beta'.encode()]==b'yes'
assert ci[b'version']==V.encode()
assert {k:v for k,v in ai.items() if k not in (b'version',b'description',b'beta')}=={k:v for k,v in ci.items() if k not in (b'version',b'description',b'beta')}
assert b'Cloudflare' in ci[b'description'] and b'wildcard' in ci[b'description'] and b'multi-domain' in ci[b'description']
unitnames=[k for k in c if k.startswith('conf/systemd/')];assert len(unitnames)==10
for n,data in d.items():
    p=R/'.build/payload'/n
    assert p.read_bytes()==data,('Assembled correspondence',n)
    assert p.stat().st_mode&0o777==int(dm[n]['mode'],8),('Assembled mode',n)
for n,data in c.items():
    if n!='package.tgz':assert (R/'.build/spk'/n).read_bytes()==data,('Outer correspondence',n)
for name in ['ui/QUICKSTART.html','ui/WORKFLOW.html','ui/RECOVERY.html']:
    text=d[name].decode()
    assert V in text and 'Public Beta' in text,name
    assert not re.search(r'0\.2\.\d+(?:-\d+)?|Development/test build',text),name
manifest={'version':V,'baseline_sha256':BASE_HASH,'spk_sha256':sha(spk.read_bytes()),'passed':True,
 'scope':'Exact byte comparison against accepted implementation; no new native run',
 'changed_payload_files':sorted(changed),'worker_sha256':sha(d['bin/sadleracme-root']),
 'helper_sha256':sha(d['bin/sadleracme-emergency-remove']),
 'unchanged_payload_files':sorted(set(d)-changed),'unchanged_systemd_units':unitnames,
 'unchanged_outer_files':sorted(set(a)-{'INFO','package.tgz'}),'cgi_only_version_and_migration_text':True,
 'metadata_only_version_description_beta':True,'payload_metadata':dm,
 'payload_sha256':{k:sha(v) for k,v in d.items()}}
(R/'tests'/f'RESULTS-{V}-package.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('PASS exact allowed changes, safe archive paths and file ownership/modes')
print('PASS unchanged launcher, workflow/theme/CSS, worker/helper, scheduler, ten units, lifecycle and vendor')
print('PASS current generated help and source/package correspondence')
print('SPK SHA256',manifest['spk_sha256'])
