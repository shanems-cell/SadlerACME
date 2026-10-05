#!/usr/bin/env python3
"""Check selected enabled-text palette pairs; not a full accessibility audit.
No screenshot sampling, composited/focus/disabled controls or native DSM chrome.
"""
from pathlib import Path
import re,json
R=Path(__file__).resolve().parents[1]
CSS=(R/'src/ui/layout.css').read_text()
def luminance(value):
    parts=[int(value[i:i+2],16)/255 for i in (1,3,5)]
    return sum((x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4)*k for x,k in zip(parts,[.2126,.7152,.0722]))
def contrast(a,b):
    lo,hi=sorted((luminance(a),luminance(b)))
    return (hi+.05)/(lo+.05)
pairs=[('text','bg'),('text','surface'),('muted','surface'),('label','surface'),('placeholder','field-bg'),('text','chrome'),('button-text','accent'),('button-text','accent2'),('button-text','warn-button-bg'),('button-text','warn-button-hover'),('nav-selected-text','selected'),('status-error-text','surface2'),('status-success-text','surface2'),('warning-text','inline-bg'),('note-text','note-bg'),('removal-text','removal-bg'),('card-heading-text','surface3'),('log-text','log-bg'),('good','badge-success-bg'),('bad','badge-error-bg'),('badge-run-text','badge-run-bg'),('badge-queue-text','badge-queue-bg')]
palette={};results=[]
for theme,block in zip(['dark','light'],re.findall(r':root[^{}]*\{([^}]+)\}',CSS)):
    palette.update(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6});',block))
    for foreground,background in pairs:
        ratio=contrast(palette[foreground],palette[background]);passed=ratio>=4.5
        results.append(dict(theme=theme,foreground=foreground,background=background,ratio=ratio,passed=passed))
        print(f"{'PASS' if passed else 'FAIL'} {theme}: {foreground} / {background}: {ratio:.3f}:1")
(R/'tests/RESULTS-1.0.0-1-theme-contrast.json').write_text(json.dumps(results,indent=2)+'\n')
print(f"{sum(r['passed'] for r in results)}/{len(results)} selected palette contrast checks passed.")
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
