#!/usr/bin/env python3
"""Fixture admission and native bridge safety; no GitLab or build execution."""

import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/nest-release-dag-fixture.py'
POLICY = runpy.run_path(str(SCRIPT))


class ReleaseDagFixtureTest(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        self.fixture = yaml.safe_load((ROOT / '.gitlab/ci/release-dag-fixture.yml').read_text())

    def test_exact_operator_modes_only(self):
        for source in ('api', 'web', 'push', 'merge_request_event', 'schedule', 'pipeline', 'parent_pipeline', 'trigger', ''):
            for mode in ('pass', 'fail', 'stage1-pass', 'stage1-fail', 'stage2-pass', 'stage2-fail', 'stage3-pass', 'stage3-fail', 'bolt-pass', 'bolt-fail', 'pdk-pass', 'pdk-fail', 'agent-pass', 'agent-fail', 'firefox-pass', 'firefox-fail', 'camofox-pass', 'camofox-fail', 'llama-pass', 'llama-fail', 'stage4-pass', 'false', 'true', '', 'PASS'):
                with self.subTest(source=source, mode=mode):
                    self.assertEqual(POLICY['admitted'](dict(CI_PIPELINE_SOURCE=source, NEST_DAG_FIXTURE=mode)),
                                     source in ('api', 'web') and mode in ('pass', 'fail', 'stage1-pass', 'stage1-fail', 'stage2-pass', 'stage2-fail', 'stage3-pass', 'stage3-fail', 'bolt-pass', 'bolt-fail', 'pdk-pass', 'pdk-fail', 'agent-pass', 'agent-fail', 'firefox-pass', 'firefox-fail', 'camofox-pass', 'camofox-fail', 'llama-pass', 'llama-fail'))

    def test_every_conflict_and_tag_refuses(self):
        for key in POLICY['CONFLICTS'] + ('CI_COMMIT_TAG',):
            for value in ('true', 'false', 'arbitrary'):
                with self.subTest(key=key, value=value):
                    env = dict(CI_PIPELINE_SOURCE='api', NEST_DAG_FIXTURE='pass', **{key: value})
                    self.assertFalse(POLICY['admitted'](env))
                    env[key] = ''
                    self.assertTrue(POLICY['admitted'](env))

    def test_real_cli_exits_no_files_no_private_values(self):
        with tempfile.TemporaryDirectory() as temp:
            for source, mode, code in (('api', 'pass', 0), ('web', 'fail', 0), ('api', 'stage1-pass', 0),
                                       ('web', 'stage1-fail', 0), ('api', 'stage2-pass', 0), ('web', 'stage2-fail', 0),
                                       ('api', 'stage3-pass', 0), ('web', 'stage3-fail', 0), ('push', 'stage3-pass', 1),
                                       ('api', 'bolt-pass', 0), ('web', 'bolt-fail', 0), ('push', 'bolt-pass', 1),
                                       ('api', 'pdk-pass', 0), ('web', 'pdk-fail', 0), ('push', 'pdk-pass', 1),
                                       ('api', 'agent-pass', 0), ('web', 'agent-fail', 0), ('push', 'agent-pass', 1),
                                       ('api', 'firefox-pass', 0), ('web', 'firefox-fail', 0), ('push', 'firefox-pass', 1),
                                       ('api', 'camofox-pass', 0), ('web', 'camofox-fail', 0), ('push', 'camofox-pass', 1),
                                       ('api', 'llama-pass', 0), ('web', 'llama-fail', 0), ('push', 'llama-pass', 1),
                                       ('push', 'stage2-pass', 1), ('push', 'stage1-pass', 1), ('push', 'pass', 1), ('api', 'false', 1)):
                env = dict(PATH=os.defpath, CI_PIPELINE_SOURCE=source, NEST_DAG_FIXTURE=mode,
                           CI_JOB_TOKEN='fixture-private-token', PYTHONDONTWRITEBYTECODE='1')
                result = subprocess.run([sys.executable, str(SCRIPT)], cwd=temp, env=env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, code)
                self.assertNotIn('fixture-private-token', result.stdout + result.stderr)
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_all_existing_jobs_suppressed_even_with_malformed_fixture(self):
        for name, job in self.config.items():
            if not isinstance(job, dict) or name in ('default',) or name.startswith('.'):
                continue
            if job.get('extends') == '.all-branch-ci':
                rules = self.config['.all-branch-ci']['rules']
            elif job.get('extends') == '.template':
                rules = self.config['.template']['rules']
            else:
                rules = job['rules']
            self.assertEqual(rules[0], {'if': r'$NEST_DAG_FIXTURE =~ /[\s\S]/', 'when': 'never'}, name)

    def test_native_bridge_has_no_command_or_inherited_pipeline_variables(self):
        for stage, prefix in (('stage0', ''), ('stage1', 'stage1-'), ('stage2', 'stage2-'), ('stage3', 'stage3-')):
            self.check_bridge(stage, prefix)
        self.check_bridge('tools/bolt', 'bolt-')
        self.check_bridge('tools/pdk', 'pdk-')
        self.check_bridge('tools/agent', 'agent-')
        self.check_bridge('tools/firefox', 'firefox-')
        self.check_bridge('tools/camofox', 'camofox-')
        self.check_bridge('tools/llama.cpp', 'llama-')

    def check_bridge(self, stage, prefix):
        name = {'tools/bolt': 'OpenBolt', 'tools/pdk': 'PDK', 'tools/agent': 'Agent', 'tools/firefox': 'Firefox', 'tools/camofox': 'Camofox', 'tools/llama.cpp': 'llama.cpp'}.get(stage, 'Stage ' + stage[-1])
        job = self.fixture[name + ' release DAG fixture']
        self.assertNotIn('script', job)
        self.assertNotIn('variables', job)  # No executing flags during rule evaluation.
        self.assertEqual(job['inherit'], {'variables': False})
        self.assertFalse(job['allow_failure'])
        self.assertEqual(job['needs'], ['Check release DAG fixture selection'])
        self.assertEqual(job['trigger'], dict(project='nest/' + stage, branch='main', strategy='mirror',
                                             forward=dict(yaml_variables=True, pipeline_variables=False)))
        guards = job['rules'][:2]
        self.assertTrue(all(guard['when'] == 'never' for guard in guards))
        conditions = ' || '.join(guard['if'] for guard in guards).split(' || ')
        for key in POLICY['CONFLICTS'] + ('CI_COMMIT_TAG',):
            self.assertIn('$' + key + r' =~ /[\s\S]/', conditions)
        for rule, mode in zip(job['rules'][2:], ('pass', 'fail')):
            expected = dict(RELEASE_DAG='true', RELEASE_VALIDATE_ONLY='true', RELEASE_DAG_FIXTURE=mode)
            if stage == 'stage3':
                expected['HOSTNAME'] = ''  # Clear Docker runtime hostname, not a host selection.
            self.assertEqual(rule['variables'], expected)
            self.assertIn('$NEST_DAG_FIXTURE == "' + prefix + mode + '"', rule['if'])
            self.assertIn('$CI_PIPELINE_SOURCE == "api"', rule['if'])
            self.assertIn('$CI_PIPELINE_SOURCE == "web"', rule['if'])
        self.assertEqual(len(job['rules']), 4)
        self.assertEqual(self.fixture['Check release DAG fixture selection']['rules'], [{'if': r'$NEST_DAG_FIXTURE =~ /[\s\S]/'}])

    def test_container_runtime_hostname_is_cleared_only_after_pipeline_admission(self):
        check = self.fixture['Check release DAG fixture selection']
        self.assertEqual(check['script'], ['env -u HOSTNAME python3 scripts/nest-release-dag-fixture.py'])
        env = dict(PATH=os.defpath, CI_PIPELINE_SOURCE='api', NEST_DAG_FIXTURE='stage3-pass',
                   HOSTNAME='fixture-container-runtime', PYTHONDONTWRITEBYTECODE='1')
        direct = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, check=False)
        self.assertEqual(direct.returncode, 1)  # A direct host selector still refuses.
        result = subprocess.run(['env', '-u', 'HOSTNAME', sys.executable, str(SCRIPT)],
                                env=env, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)

    def test_artifact_backed_nested_bridges_disable_all_caller_forwarding(self):
        compile_job = self.fixture['Compile nested DAG fixture']
        bridge = self.fixture['Run nested DAG fixture']
        self.assertEqual(compile_job['needs'], ['Check release DAG fixture selection'])
        self.assertEqual(compile_job['script'], ['env -u HOSTNAME python3 scripts/nest-release-dag-fixture.py --compile-nested'])
        self.assertEqual(compile_job['artifacts'], {'when': 'on_success', 'paths': ['nested-dag-fixture/']})
        self.assertEqual(bridge['needs'], ['Compile nested DAG fixture'])
        self.assertEqual(bridge['inherit'], {'variables': False})
        self.assertFalse(bridge['allow_failure'])
        self.assertEqual(bridge['trigger'], dict(include=[dict(artifact='nested-dag-fixture/child.yml',
                                                              job='Compile nested DAG fixture')],
                                               strategy='mirror', forward=dict(yaml_variables=False, pipeline_variables=False)))
        self.assertEqual(bridge['rules'], compile_job['rules'])
        self.assertNotIn('variables', bridge)
        for key in POLICY['CONFLICTS'] + ('CI_COMMIT_TAG',):
            self.assertTrue(any('$' + key + r' =~ /[\s\S]/' in rule['if'] for rule in bridge['rules'][:2]), key)

    def test_frozen_candidate_route_is_artifact_backed_required_and_explicit(self):
        route = yaml.safe_load((ROOT / '.gitlab/ci/release-routing.yml').read_text())['Route frozen candidate']
        self.assertEqual(route['needs'], ['Freeze release inputs'])
        self.assertFalse(route['allow_failure'])
        self.assertEqual(route['inherit'], {'variables': False})
        self.assertEqual(route['trigger'], {
            'include': [{'artifact': 'release-inputs/candidate.yml', 'job': 'Freeze release inputs'}],
            'strategy': 'mirror', 'forward': {'yaml_variables': False, 'pipeline_variables': False}})
        self.assertNotIn('script', route)
        selection = route['rules'][-1]['if']
        self.assertIn('$RELEASE_INPUTS == "true"', selection)
        self.assertIn('$RELEASE_ROUTE == "true"', selection)
        for source in ('api', 'web', 'pipeline', 'trigger'):
            self.assertIn('$CI_PIPELINE_SOURCE == "' + source + '"', selection)

    def test_bootstrap_route_is_isolated_from_status_fixtures_and_caller_variables(self):
        route = yaml.safe_load((ROOT / '.gitlab/ci/executor-bootstrap.yml').read_text())
        compiler, bridge = route['Compile executor bootstrap'], route['Run executor bootstrap']
        self.assertIn({'local': '.gitlab/ci/executor-bootstrap.yml'}, self.config['include'])
        self.assertEqual(compiler['rules'], bridge['rules'])
        self.assertEqual(compiler['rules'][0], {'if': r'$NEST_DAG_FIXTURE =~ /[\s\S]/', 'when': 'never'})
        self.assertEqual(compiler['rules'][1], {'if': '$CI_COMMIT_TAG', 'when': 'never'})
        self.assertIn('$CI_COMMIT_BRANCH == "main"', compiler['rules'][-1]['if'])
        self.assertIn('$EXECUTOR_BOOTSTRAP == "route"', compiler['rules'][-1]['if'])
        self.assertNotIn('script', bridge)
        self.assertEqual(bridge['needs'], ['Compile executor bootstrap'])
        self.assertEqual(bridge['inherit'], {'variables': False})
        self.assertFalse(bridge['allow_failure'])
        self.assertEqual(bridge['trigger'], dict(include=[dict(artifact='executor-bootstrap-route/child.yml',
                                                              job='Compile executor bootstrap')],
                                               strategy='mirror', forward=dict(yaml_variables=False, pipeline_variables=False)))
        self.assertNotIn('variables', bridge)

    def test_any_routing_field_prevents_default_executor_build_and_deployment(self):
        routing = runpy.run_path(str(ROOT / 'scripts/nest-release-route.py'))
        for name in ('.template', 'Deploy image', 'Deploy environment'):
            rules = self.config[name]['rules']
            guards = [rule['if'] for rule in rules if rule.get('when') == 'never']
            for key in routing['ROUTE_KEYS']:
                self.assertTrue(any('$' + key + r' =~ /[\s\S]/' in guard for guard in guards), (name, key))
        check = self.config['Check release route selection']
        self.assertEqual(check['stage'], 'Test')
        self.assertEqual(check['script'], ['python3 scripts/nest-release-route.py --check-selection'])
        self.assertEqual(check['rules'][0], {'if': r'$NEST_DAG_FIXTURE =~ /[\s\S]/', 'when': 'never'})


if __name__ == '__main__':
    unittest.main()
