"""Render one auditable worker; no runtime source from package-writable files."""
from pathlib import Path
import sys

def render_worker(root):
    root=Path(root)
    text=(root/'src/bin/sadleracme-root').read_text()
    marker='# @WORKER_EXTENSIONS@'
    if text.count(marker)!=1:
        raise ValueError('Expected exactly one worker extension marker')
    parts=[]
    for p in sorted((root/'src/lib').glob('*.sh')):
        parts.append('\n# BEGIN '+p.name+'\n'+p.read_text()+'\n# END '+p.name+'\n')
    return render_storage_helpers(root, text.replace(marker,'\n'.join(parts)))

def render_storage_helpers(root, text):
    return text.replace('# @PACKAGE_STORAGE_HELPERS@',
                        (Path(root)/'src/lib/package-storage.sh').read_text())

def render_emergency(root):
    root=Path(root)
    text=(root/'src/bin/sadleracme-emergency-remove').read_text()
    if text.count('# @PACKAGE_STORAGE_HELPERS@')!=1:
        raise ValueError('Expected one emergency package-storage marker')
    return render_storage_helpers(root, text)

def render_cgi(root):
    root=Path(root)
    text=(root/'src/ui/index.cgi').read_text()
    marker='# @CGI_EXTENSIONS@'
    if text.count(marker)!=1:
        raise ValueError('Expected one CGI extension marker')
    return text.replace(marker,(root/'src/ui/workflow-api.sh').read_text())

if __name__=='__main__':
    kind=sys.argv[3] if len(sys.argv)>3 else 'worker'
    renderer={'worker':render_worker,'cgi':render_cgi,'emergency':render_emergency}[kind]
    Path(sys.argv[2]).write_text(renderer(sys.argv[1]))
