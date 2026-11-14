"""Static consumer contract checks without importing live tool registration."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


def schemas():
    tree = ast.parse((ROOT / 'files/app/hermes/secure_browser_tool.py').read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.AnnAssign)
                      and isinstance(node.target, ast.Name) and node.target.id == 'SCHEMAS')
    assert isinstance(assignment.value, ast.List)
    return {value['name']: value for row in assignment.value.elts
            for value in [ast.literal_eval(row.elts[0])]}


class FirefoxV3ConsumerContractTests(unittest.TestCase):
    def test_managed_skill_describes_actual_window_binding_and_no_replay(self):
        skill = (ROOT / 'files/app/hermes/skills/star-firefox-ui/SKILL.md').read_text()
        for phrase in ('firefox-windows-v3', 'CSS selector', 'owner window', 'nonallocating',
                       'uncertain', 'same native transport', 'action_key', 'lease_seconds',
                       'document.readText', 'legacy AX', 'Joy\'s direction'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)
        self.assertNotIn('require `protocol=firefox-ui-v1`', skill)
        self.assertNotIn('all instrumentation flags false', skill)
        self.assertNotIn('CSS selectors are deliberately unsupported', skill)
        self.assertNotIn('without browser-internal automation', skill)

    def test_each_affected_public_description_declares_v3(self):
        public = schemas()
        for name in ('status', 'navigate', 'page_snapshot', 'current_page_summary', 'wait_for_stable',
                     'checkout_readback', 'scroll', 'query', 'screenshot', 'visual_evidence',
                     'click', 'type', 'tab_lifecycle', 'guardrail_check'):
            with self.subTest(name=name):
                self.assertIn('v3', public['secure_browser_' + name]['description'].lower())
        for name in ('click', 'type'):
            self.assertIn('v3', public['secure_browser_' + name]['parameters']['properties']['selector']['description'])
        self.assertIn('not independent', public['secure_browser_navigate']['description'])
        self.assertIn('nonallocating', public['secure_browser_tab_lifecycle']['description'])


if __name__ == '__main__':
    unittest.main()
