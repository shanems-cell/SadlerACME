#!/usr/bin/env python3
"""Shared layout assertions; insensitive to readable CSS formatting."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'src/ui/index.cgi').read_text()
def compact_css(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*([{}:;,>])\s*', r'\1', text)
    return re.sub(r';}', '}', text).replace('@media (', '@media(')
LAYOUT_RAW = (ROOT / 'src/ui/layout.css').read_text()
WORKFLOW_RAW = (ROOT / 'src/ui/workflow.css').read_text()
LAYOUT = compact_css(LAYOUT_RAW)
WORKFLOW = compact_css(WORKFLOW_RAW)
WORKFLOW_JS = (ROOT / 'src/ui/workflow.js').read_text()
WORKER = (ROOT / 'src/bin/sadleracme-root').read_text()

class LayoutCommon(unittest.TestCase):
    def test_shared_card_system_is_in_layout_css(self):
        self.assertIn('.card{', LAYOUT)
        self.assertIn('.card>h2{', LAYOUT)
        self.assertIn('.card-footer{', LAYOUT)
        self.assertIn('.kvgrid{', LAYOUT)

    def test_normal_page_grids_share_layout_css(self):
        self.assertIn('.section-grid,.automation-grid,.dashboard,.workflow-recovery-grid{', LAYOUT)
        self.assertIn('.workflow-facts{', LAYOUT)

    def test_workflow_css_does_not_own_recovery_page_grid(self):
        self.assertNotRegex(WORKFLOW, r'#tab-(?:backup|uninstall)\s+\.workflow-recovery-grid')
        self.assertNotIn('.workflow-facts{', WORKFLOW)
        self.assertIn('Recovery pages use the common panel/grid system in layout.css', WORKFLOW_RAW)

    def test_dashboard_status_actions_are_consolidated(self):
        dashboard = INDEX.split('<div id="tab-dashboard"',1)[1].split('<div id="tab-settings"',1)[0]
        self.assertIn('class="card statuscard dashboard-status"', dashboard)
        self.assertIn('id="statusRefreshBtn"', dashboard)
        self.assertIn('id="viewLogBtn"', dashboard)
        self.assertNotIn('class="status-freshness"', dashboard)

    def test_check_now_is_in_renewal_panel_footer(self):
        dashboard = INDEX.split('<div id="tab-dashboard"',1)[1].split('<div id="tab-settings"',1)[0]
        self.assertIn('class="card-footer renewal-actions"', dashboard)
        self.assertIn('name="action" value="check"', dashboard)
        self.assertNotIn('<h2>Renewal check</h2>', dashboard)

    def test_automation_is_three_peer_cards(self):
        automation = INDEX.split('<div id="tab-automation"',1)[1].split('<div id="schedulerInstallModal"',1)[0]
        self.assertNotIn('class="workflow-stack"', automation)
        self.assertGreaterEqual(automation.count('class="card"'), 3)
        self.assertIn('<h2>Background processing</h2>', automation)
        self.assertIn('<h2>Automatic renewal</h2>', automation)
        self.assertIn('<h2>Boot-up task configuration</h2>', automation)

    def test_responsive_navigation_is_retained(self):
        self.assertIn('id="menuToggle"', INDEX)
        self.assertIn('class="topnav tabs"', INDEX)
        self.assertRegex(LAYOUT, r'@media\(max-width:820px\).*#menuToggle\{display:inline-flex\}')


    def test_peer_cards_stretch_to_equal_height(self):
        self.assertIn('align-items:stretch', LAYOUT)
        self.assertIn('height:100%', LAYOUT)
        self.assertIn('.section-grid>.card>.card-footer,.automation-grid>.card>.card-footer,.workflow-recovery-grid>.card>.card-footer{margin-top:auto}', LAYOUT)

    def test_shared_density_is_compact_without_tiny_text(self):
        self.assertIn('--page-gap:10px;--panel-pad:9px', LAYOUT)
        self.assertIn('textarea{min-height:64px', LAYOUT)
        self.assertIn('min-height:29px', LAYOUT)

    def test_peer_headers_have_consistent_minimum_height(self):
        self.assertRegex(LAYOUT, r'\.card>h2\{[^}]*min-height:31px')


    def test_release_examples_are_generic(self):
        self.assertIn('placeholder="example.com&#10;*.example.com"', INDEX)
        self.assertNotIn('placeholder="sadlernet.com&#10;*.sadlernet.com"', INDEX)

    def test_wizard_polish_for_fresh_setup(self):
        self.assertIn('Temporary setup processing was started for this wizard.', WORKFLOW_JS)
        self.assertIn('This can take a couple of minutes; please wait.', WORKER)
        self.assertIn('#workflowWorkerControls{margin-top:14px}', WORKFLOW)

    def test_common_layout_has_compact_dashboard_breakpoints(self):
        self.assertIn('.dashboard{grid-template-columns:repeat(3,minmax(0,1fr))}', LAYOUT)
        self.assertIn('@media(max-width:920px){.dashboard{grid-template-columns:repeat(2,minmax(0,1fr))}', LAYOUT)

if __name__ == '__main__':
    unittest.main(verbosity=2)
