#!/usr/bin/env python3
"""Check stylesheet ownership and basic maintenance contracts (static only)."""
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
LAYOUT=(ROOT/'src/ui/layout.css').read_text()
WORKFLOW=(ROOT/'src/ui/workflow.css').read_text()
INDEX=(ROOT/'src/ui/index.cgi').read_text()
def without_comments(s):
    return re.sub(r'/\*.*?\*/','',s,flags=re.S)
L,W=map(without_comments,(LAYOUT,WORKFLOW))
class CSSMaintenance(unittest.TestCase):
    def test_stylesheet_load_order(self):
        self.assertLess(INDEX.index('href="layout.css?'),INDEX.index('href="workflow.css?'))
    def test_theme_has_one_definition_per_variable(self):
        # Two palettes intentionally override colour tokens; each block has
        # one definition per name. Shared layout variables remain dark-root defaults.
        for block in re.findall(r':root[^{}]*\{([^}]+)\}',L):
            definitions=re.findall(r'(--[a-zA-Z0-9-]+)\s*:',block)
            self.assertEqual(len(definitions),len(set(definitions)))
        self.assertFalse(re.search(r'--[\w-]+\s*:',W))
    def test_all_custom_property_references_exist(self):
        definitions=set(re.findall(r'(--[\w-]+)\s*:',L+W))
        references=set(re.findall(r'var\(\s*(--[\w-]+)',L+W))
        self.assertFalse(references-definitions, references-definitions)
    def test_shared_action_row_is_in_layout(self):
        self.assertRegex(L,r'\.actions,\s*\.workflow-buttons\s*\{')
        self.assertNotRegex(W,r'(?m)^\.workflow-buttons\s*\{')
        self.assertIn('gap: var(--action-gap)',L)
    def test_shared_status_colours_have_one_owner(self):
        for selector in ['.workflow-status.error','.workflow-status.success']:
            self.assertIn(selector,L);self.assertNotIn(selector,W)
        for colour in ['#895156','#f0b1b1','#487056','#a5dfb6']:
            self.assertNotIn(colour,W)
    def test_shared_log_surface_has_one_owner(self):
        self.assertRegex(L,r'\.log,\s*\.workflow-log\s*\{')
        rule=re.search(r'\.workflow-log\s*\{([^}]+)}',W).group(1)
        self.assertIn('height: 100%',rule)
        self.assertIn('min-height: 0',rule)
        for name in ['background:','font:','border:','padding:']:
            self.assertNotIn(name,rule)
    def test_decorative_inline_css_is_removed(self):
        self.assertNotRegex(INDEX,r'style="(?:margin|cursor|white-space)')
        self.assertIn('style="display:none"',INDEX) # existing server action-visibility guard
        for cls in ['field-help','action-explanation','scheduler-explanation','disclosure-heading','manual-help-note','approval-help','licence-text']:
            self.assertIn(cls,INDEX);self.assertIn('.'+cls,L)
    def test_workflow_hidden_reuses_common_rule(self):
        self.assertIn('[hidden]',L);self.assertNotIn('[hidden]',W)
    def test_both_files_are_readable_and_documented(self):
        self.assertIn('SHARED STYLES',LAYOUT);self.assertIn('WORKFLOW ARRANGEMENTS',WORKFLOW)
        for css in [LAYOUT,WORKFLOW]:
            self.assertIn('Index:',css)
            # Every declaration ends on its own line, rather than one minified block.
            self.assertFalse(any(line.count(';')>1 for line in without_comments(css).splitlines()))
if __name__=='__main__':unittest.main(verbosity=2)
