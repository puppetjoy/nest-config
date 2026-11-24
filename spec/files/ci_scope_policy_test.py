#!/usr/bin/env python3
"""Non-mutating checks for routine CI ownership and image build selection."""

from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class CiScopePolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ci = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())

    def test_default_executor_builds_are_limited_to_executor_inputs(self):
        expected = {'Containerfile', 'Puppetfile', 'bolt-project.yaml', 'bin/ci-bolt-module-install', 'bin/build',
                    'files/build/**/*', 'scripts/nest-executor-bootstrap.py',
                    'scripts/nest-executor-inputs.py'}
        for name in ('.template', 'Deploy image'):
            rules = self.ci[name]['rules']
            matching = [rule for rule in rules if rule.get('changes')]
            self.assertEqual(len(matching), 1, name)
            self.assertEqual(set(matching[0]['changes']), expected, name)

    def test_app_lanes_only_run_for_owned_paths_and_skip_duplicate_pushes(self):
        joyride = self.ci['Joyride private access']['rules']
        firefox = self.ci['Secure browser fixtures']['rules']
        window = self.ci['Secure browser window fixtures']['rules']
        native = self.ci['Firefox Native authority fixtures']['rules']
        self.assertEqual(joyride[0], {'if': r'$NEST_DAG_FIXTURE =~ /[\s\S]/', 'when': 'never'})
        self.assertEqual(joyride[1], {'if': '$CI_PIPELINE_SOURCE == "push" && $CI_OPEN_MERGE_REQUESTS', 'when': 'never'})
        expected_joyride = {'data/kubernetes/app/joyride/**/*', 'data/kubernetes/app/joyride.yaml',
                            'data/kubernetes/service/joyride*.yaml', 'data/kubernetes/service/joyride/**/*',
                            'files/app/joyride/**/*', 'manifests/service/joyride.pp',
                            'plans/eyrie/deploy_joyride*.yaml', 'spec/app/joyride/**/*'}
        self.assertEqual(set(joyride[2]['changes']), expected_joyride)
        self.assertEqual(firefox[2]['changes'], window[2]['changes'])
        self.assertEqual(firefox[2]['changes'], native[2]['changes'])
        self.assertIn('files/firefox-browser/**/*', firefox[2]['changes'])
        self.assertIn('files/app/hermes/*browser*.py', firefox[2]['changes'])
        self.assertIn('spec/app/hermes/native_authority/**/*', firefox[2]['changes'])
        for rules in (firefox, window, native):
            self.assertEqual(rules[0], joyride[0])
            self.assertEqual(rules[1], joyride[1])

    def test_environment_deploy_is_independent_of_executor_artifacts(self):
        job = self.ci['Deploy environment']
        self.assertNotIn('needs', job)
        self.assertEqual(job['script'][-1], 'bolt plan run nest::puppet::deploy backend=prod environment="$CI_COMMIT_BRANCH"')
        self.assertEqual(job['resource_group'], 'puppet-code-deployment')
        self.assertIn({'if': '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'}, job['rules'])

    def test_explicit_build_and_executor_modes_remain_admitted(self):
        rules = self.ci['.template']['rules']
        self.assertTrue(any('$EXECUTOR_ONLY == "true" && $BUILD == $CPU' in rule.get('if', '') for rule in rules))
        self.assertTrue(any('$CI_PIPELINE_SOURCE == "parent_pipeline"' in rule.get('if', '') for rule in rules))
        self.assertTrue(any('$EXECUTOR_BOOTSTRAP == "true"' in rule.get('if', '') for rule in rules))


if __name__ == '__main__':
    unittest.main()
