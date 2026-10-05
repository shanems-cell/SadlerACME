"""Build self-contained package help using only the Python standard library."""
from pathlib import Path
import html
import re
import sys


def inline(value):
    value = html.escape(value, quote=True)
    value = re.sub(r'`([^`]+)`', r'<code>\1</code>', value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
    # Only local packaged guides and HTTPS links are navigable.
    def link(match):
        label, target = match.groups()
        if target in ('RECOVERY.md', 'QUICKSTART.md', 'WORKFLOW.md'):
            target = target[:-3] + '.html'
        elif not target.startswith('https://'):
            return label + ' (' + target + ')'
        return '<a href="' + target + '">' + label + '</a>'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)


def render(text):
    blocks, paragraph, code = [], [], None
    list_kind = None

    def flush():
        if paragraph:
            blocks.append('<p>' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()

    def close_list():
        nonlocal list_kind
        if list_kind:
            blocks.append('</' + list_kind + '>')
            list_kind = None

    for line in text.splitlines():
        if line.startswith('```'):
            flush()
            close_list()
            if code is None:
                code = []
            else:
                blocks.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        heading = re.match(r'^(#{1,6}) (.*)$', line)
        item = re.match(r'^(?:([-*]) |(\d+)\. )(.*)$', line)
        if heading:
            flush()
            close_list()
            level = str(len(heading[1]))
            blocks.append('<h' + level + '>' + inline(heading[2]) + '</h' + level + '>')
        elif item:
            flush()
            kind = 'ul' if item[1] else 'ol'
            if list_kind != kind:
                close_list()
                blocks.append('<' + kind + '>')
                list_kind = kind
            blocks.append('<li>' + inline(item[3]) + '</li>')
        elif line.startswith('|'):
            flush()
            close_list()
            if not re.match(r'^\|[\s:|\-]+$', line):
                cells = [cell.strip() for cell in line.strip('|').split('|')]
                blocks.append('<p class="table-row">' + ' — '.join(inline(c) for c in cells) + '</p>')
        elif line.strip():
            close_list()
            paragraph.append(line.strip())
        else:
            flush()
            close_list()
    flush()
    close_list()
    if code is not None:
        raise ValueError('Unclosed code fence in documentation')
    return '\n'.join(blocks)


root, destination = map(Path, sys.argv[1:])
version = re.search(r'^version="([^"]+)"', (root / 'pkg/INFO').read_text(), re.M).group(1)
for name in ('QUICKSTART', 'WORKFLOW', 'RECOVERY'):
    content = render((root / (name + '.md')).read_text())
    output = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SadlerACME — ''' + name.title() + '''</title><style>
body{font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#182536;background:#fff}
a{color:#0759a5}nav{display:flex;flex-wrap:wrap;gap:16px;border-bottom:1px solid #ccd5df;padding-bottom:16px}
h1,h2,h3{line-height:1.25;margin-top:1.6em}li{margin:.5em 0}code{font-family:ui-monospace,monospace;overflow-wrap:anywhere}
pre{padding:16px;background:#f0f3f7;border:1px solid #d4dce6;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}
.warning{border-left:4px solid #b42318;padding:12px;background:#fff3f2;color:#8c1b13}.table-row{border-bottom:1px solid #ddd;padding:8px}
</style></head><body><nav><a href="QUICKSTART.html">QuickStart</a><a href="WORKFLOW.html">Workflow</a><a href="RECOVERY.html">Recovery and removal</a>
<a href="sadleracme-emergency-remove.txt" download="sadleracme-emergency-remove">Download SSH recovery script</a></nav>
<p class="warning"><strong>SadlerACME ''' + html.escape(version) + ''' — Public Beta.</strong> Cloudflare DNS is required. Read the removal instructions before using the emergency script. Recovery backups can contain private keys.</p>
''' + content + '</body></html>\n'
    (destination / (name + '.html')).write_text(output)
