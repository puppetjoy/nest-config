"""Compiler publication contracts with inert receipts and fake Podman only."""
import copy
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/nest-compiler-candidate.py'
MODULE = runpy.run_path(str(SCRIPT))
SHA = 'a' * 40
REPOSITORY = 'registry.gitlab.joyfullee.me/nest/config/main'
INDEX = 'registry.eyrie/nest/config/main@sha256:' + 'f' * 64
EXPECTED = dict(schema=1, environment='main', source=SHA, code_id='sha256:' + 'e' * 64)


def member(cpu, number):
    return dict(schema=2, kind='nest_config_executor_member', project='nest/config', sha=SHA, pipeline=123,
                job=100 + number, cpu=cpu, image=REPOSITORY + '@sha256:' + format(number, '064x'),
                source_verification='git_head_and_oci_revision',
                inputs=dict(schema=1, kind='nest_config_executor_inputs', source=SHA,
                            base_image='registry.example/nest/tools/bolt@sha256:' + 'd' * 64,
                            puppetfile_digest='sha256:' + 'c' * 64,
                            modules=[dict(name=name, git_head=SHA if name == 'nest' else None,
                                          content_digest='sha256:' + 'b' * 64)
                                     for name in ('nest', 'stdlib', 'reboot', 'ruby_task_helper', 'private', 'kubecm')]))


class CompilerCandidateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = dict(CI_PROJECT_PATH='nest/config', CI_COMMIT_SHA=SHA, CI_PIPELINE_ID='123',
                        CI_REGISTRY_IMAGE='registry.gitlab.joyfullee.me/nest/config', CI_COMMIT_REF_SLUG='main',
                        CI_COMMIT_BRANCH='main', CPU='haswell', CI_JOB_ID='101')
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.rows = []
        for number, cpu in enumerate(MODULE['CPUS'], 1):
            row = dict(schema=1, executor=member(cpu, number), expected=copy.deepcopy(EXPECTED))
            self.rows.append(row)
            self.save(cpu + '.compiler.json', row)
        self.index = dict(schemaVersion=2, mediaType='application/vnd.oci.image.index.v1+json', manifests=[
            dict(mediaType='application/vnd.oci.image.manifest.v1+json', size=1000,
                 digest=row['executor']['image'].split('@')[1],
                 platform=dict(os='linux', architecture=MODULE['CPUS'][row['executor']['cpu']])) for row in self.rows])
        self.output = self.root / 'candidate.json'

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def candidate(self):
        return MODULE['candidate'](self.root, INDEX, self.output)

    def test_complete_three_architecture_candidate_reopens_exact_output_without_authorizing_deployment(self):
        with patch.object(MODULE['subprocess'], 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            value = self.candidate()
        self.assertEqual(json.loads(self.output.read_bytes()), value)
        self.assertEqual(value['current'], dict(image=INDEX, expected=EXPECTED))
        self.assertNotIn('retained', value)
        for field in ('deployment_authorized', 'retention_complete', 'compiler_attestation'):
            self.assertIs(value[field], False)
        self.assertEqual(execute.call_args.args[0], ['podman', 'manifest', 'inspect', INDEX])

    def test_native_record_reads_only_exact_digest_with_no_source_or_secret_mounts(self):
        path = self.save('executor.json', self.rows[0]['executor'])
        output = self.root / 'member.compiler.json'
        native = dict(expected=EXPECTED, inputs=self.rows[0]['executor']['inputs'])
        with patch.object(MODULE['subprocess'], 'run') as execute:
            execute.return_value.stdout = json.dumps(native)
            MODULE['record'](path, output)
        self.assertEqual(json.loads(output.read_bytes()), self.rows[0])
        calls = execute.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0], ['podman', 'pull', self.rows[0]['executor']['image']])
        argv = calls[1].args[0]
        for flag in ('--network=none', '--read-only', '--read-only-tmpfs=false', '--pull=never', '--cap-drop=ALL'):
            self.assertIn(flag, argv)
        self.assertFalse(any(arg.startswith(('--volume', '--mount', '--env')) for arg in argv))
        self.assertIn('NestPuppetVersionedCode::Snapshot.new', argv[-2])
        self.assertEqual([call.kwargs['timeout'] for call in calls], [600, 180])

    def test_record_refuses_wrong_job_or_cpu_before_any_native_command(self):
        path = self.save('executor.json', self.rows[1]['executor'])
        with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
            MODULE['record'](path, self.output)
        execute.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_record_refuses_wrong_native_source_tree_or_inputs_without_output(self):
        path = self.save('executor.json', self.rows[0]['executor'])
        cases = [dict(expected=dict(EXPECTED, source='b' * 40), inputs=self.rows[0]['executor']['inputs']),
                 dict(expected=EXPECTED, inputs={}), dict(expected=dict(EXPECTED, schema=True), inputs=self.rows[0]['executor']['inputs'])]
        for native in cases:
            with self.subTest(native=native), patch.object(MODULE['subprocess'], 'run') as execute:
                execute.return_value.stdout = json.dumps(native)
                with self.assertRaises(ValueError):
                    MODULE['record'](path, self.output)
                self.assertFalse(self.output.exists())

    def test_malformed_or_cross_pipeline_member_refuses_before_registry(self):
        for mutate in (lambda row: row.update(schema=True), lambda row: row['executor'].update(pipeline=122),
                       lambda row: row['executor'].update(cpu='haswell'), lambda row: row['executor'].update(job=101),
                       lambda row: row['executor'].update(image=self.rows[0]['executor']['image']),
                       lambda row: row['expected'].update(code_id='sha256:' + 'd' * 64),
                       lambda row: row['expected'].update(source='b' * 40), lambda row: row['expected'].update(schema=True),
                       lambda row: row['executor']['inputs']['modules'][0].update(content_digest='sha256:' + 'c' * 64),
                       lambda row: row['executor']['inputs'].update(puppetfile_digest='sha256:' + 'b' * 64),
                       lambda row: row.update(extra='private-secret')):
            row = copy.deepcopy(self.rows[1])
            mutate(row)
            self.save('cortex-a53.compiler.json', row)
            with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
                self.candidate()
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_missing_duplicate_keys_and_oversized_input_refuse(self):
        path = self.root / 'haswell.compiler.json'
        for payload in ('{"schema":1,"schema":1}', ' ' * 131073):
            path.write_text(payload)
            with self.assertRaises(ValueError):
                self.candidate()
        path.unlink()
        with self.assertRaises(OSError):
            self.candidate()
        self.assertFalse(self.output.exists())

    def test_mutable_foreign_and_branch_index_references_refuse_before_registry(self):
        for reference in ('registry.eyrie/nest/config/main:latest', REPOSITORY + '@sha256:' + 'f' * 64,
                          INDEX + '\n', INDEX.replace('/main@', '/other@')):
            with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
                MODULE['candidate'](self.root, reference, self.output)
            execute.assert_not_called()
        with patch.dict(os.environ, CI_COMMIT_BRANCH='other'), self.assertRaises(ValueError):
            self.candidate()
        self.assertFalse(self.output.exists())

    def test_index_wrong_missing_duplicate_extra_members_or_platforms_refuse(self):
        for mutate in (lambda index: index.update(schemaVersion=True), lambda index: index.update(mediaType='text/plain'),
                       lambda index: index['manifests'].pop(), lambda index: index['manifests'].append(index['manifests'][0]),
                       lambda index: index['manifests'][0].update(digest='sha256:' + '0' * 64),
                       lambda index: index['manifests'][0].update(size=True),
                       lambda index: index['manifests'][0].update(mediaType='application/vnd.oci.image.index.v1+json'),
                       lambda index: index['manifests'][1]['platform'].update(architecture='amd64'),
                       lambda index: index['manifests'][0]['platform'].update(os='windows'),
                       lambda index: index['manifests'][0]['platform'].update(variant='v8'),
                       lambda index: index['manifests'][1]['platform'].update(variant='v9'),
                       lambda index: index['manifests'][1]['platform'].update(features=['unknown'])):
            index = copy.deepcopy(self.index)
            mutate(index)
            with patch.object(MODULE['subprocess'], 'run') as execute:
                execute.return_value.stdout = json.dumps(index)
                with self.assertRaises(ValueError):
                    self.candidate()
                self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.write_text('previous')
        with patch.object(MODULE['subprocess'], 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            with self.assertRaises(FileExistsError):
                self.candidate()
        self.assertEqual(self.output.read_text(), 'previous')

    def test_cli_native_failure_is_sanitized_and_emits_no_candidate(self):
        # Real CLI and inert executable, not a mocked successful receipt.
        podman = self.root / 'podman'
        podman.write_text('#!/bin/sh\nprintf private-secret-native-error >&2\nexit 37\n')
        podman.chmod(0o755)
        env = dict(self.env, PATH=str(self.root) + os.pathsep + os.defpath)
        result = subprocess.run([sys.executable, str(SCRIPT), 'candidate', str(self.root), INDEX, str(self.output)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('private-secret', result.stderr)
        self.assertFalse(self.output.exists())

    def test_ci_publishes_candidate_after_exact_mirror_digest_not_latest(self):
        ci = (ROOT / '.gitlab-ci.yml').read_text()
        self.assertIn('nest-compiler-candidate.py record', ci)
        deploy = ci.split("'Deploy image':", 1)[1].split("'Check executor bootstrap selection':", 1)[0]
        self.assertIn('--digestfile compiler-candidates/index.digest', deploy)
        self.assertIn('nest-compiler-candidate.py candidate', deploy)
        self.assertIn('paths: [\'compiler-candidates/\']', deploy)
        self.assertNotIn('compiler_release=', deploy)

    def pin(self, value):
        return MODULE['pin'](self.save('pin-candidate.json', value), REPOSITORY + ':manifest-123', self.output)

    def pin_command(self, argv, _phase, timeout=180):
        self.pin_calls.append(argv)
        if argv[:3] == ['podman', 'manifest', 'push']:
            Path(argv[argv.index('--digestfile') + 1]).write_text(self.pin_digest)
            self.assertEqual(timeout, 600)
            return ''
        return json.dumps(self.index)

    def test_pin_adds_only_digest_named_mirror_tag_and_reopens_it(self):
        value, _previous = self.selection_fixture()
        self.pin_calls, self.pin_digest = [], 'sha256:' + 'f' * 64
        with patch.dict(MODULE['pin'].__globals__, command=self.pin_command):
            result = self.pin(value)
        tag = 'registry.eyrie/nest/config/main:compiler-sha256-' + 'f' * 64
        self.assertEqual(result['tag'], tag)
        self.assertEqual(result['image'], INDEX)
        self.assertEqual(json.loads(self.output.read_bytes()), result)
        self.assertFalse(result['retention_complete'])
        self.assertFalse(result['deployment_authorized'])
        push = self.pin_calls[-2]
        self.assertEqual(push[:5], ['podman', 'manifest', 'push', '--all', '--digestfile'])
        self.assertEqual(push[-2:], [REPOSITORY + ':manifest-123', tag])
        self.assertEqual(self.pin_calls[-1], ['podman', 'manifest', 'inspect', tag])
        self.assertFalse(any('latest' in arg or 'prune' in arg for call in self.pin_calls for arg in call))

    def test_pin_refuses_wrong_ci_context_local_list_or_existing_output_before_registry(self):
        value, _previous = self.selection_fixture()
        for env in ({'CI_COMMIT_BRANCH': 'other'}, {'CI_COMMIT_SHA': 'b' * 40}, {'CI_PIPELINE_ID': '124'}):
            with patch.dict(os.environ, env), patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
                self.pin(value)
            execute.assert_not_called()
        path = self.save('pin-candidate.json', value)
        for local in ('--all', REPOSITORY + ':latest', REPOSITORY + ':manifest-124'):
            with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
                MODULE['pin'](path, local, self.output)
            execute.assert_not_called()
        self.output.write_text('prior')
        with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
            self.pin(value)
        execute.assert_not_called()
        self.assertEqual(self.output.read_text(), 'prior')

    def test_pin_accepts_only_native_zstd_descriptor_additions_with_exact_pushed_digest(self):
        value, _previous = self.selection_fixture()
        remote = copy.deepcopy(self.index)
        for item in remote['manifests']:
            item['annotations'] = {'io.github.containers.compression.zstd': 'true'}
        self.pin_calls, self.pin_digest = [], 'sha256:' + 'f' * 64

        def command(argv, phase, timeout=180):
            if argv[:3] == ['podman', 'manifest', 'push']:
                return self.pin_command(argv, phase, timeout)
            return json.dumps(self.index if argv[-1] == REPOSITORY + ':manifest-123' else remote)

        with patch.dict(MODULE['pin'].__globals__, command=command):
            result = self.pin(value)
        self.assertTrue(result['published_digest_verified'])
        self.assertTrue(result['tag_readback_verified'])

    def test_pin_refuses_other_descriptor_drift_and_conflicting_compression_hints(self):
        value, _previous = self.selection_fixture()
        for mutate in (lambda item: item.update(annotations={'io.github.containers.compression.zstd': 'false'}),
                       lambda item: item.update(annotations={'unknown': 'true'}),
                       lambda item: item.update(size=1001),
                       lambda item: item['platform'].update(variant='v8')):
            remote = copy.deepcopy(self.index)
            mutate(remote['manifests'][1])
            calls = []

            def command(argv, phase, timeout=180):
                calls.append(argv)
                return json.dumps(self.index if argv[-1] == REPOSITORY + ':manifest-123' else remote)

            with patch.dict(MODULE['pin'].__globals__, command=command), self.assertRaises(ValueError):
                self.pin(value)
            self.assertFalse(any('push' in call for call in calls))
            self.assertFalse(self.output.exists())

        local = copy.deepcopy(self.index)
        local['manifests'][0]['annotations'] = {'io.github.containers.compression.zstd': 'false'}
        remote = copy.deepcopy(self.index)
        remote['manifests'][0]['annotations'] = {'io.github.containers.compression.zstd': 'true'}
        calls = []

        def conflicting(argv, phase, timeout=180):
            calls.append(argv)
            return json.dumps(local if argv[-1] == REPOSITORY + ':manifest-123' else remote)

        with patch.dict(MODULE['pin'].__globals__, command=conflicting), self.assertRaises(ValueError):
            self.pin(value)
        self.assertFalse(any('push' in call for call in calls))
        self.assertFalse(self.output.exists())

    def test_pin_refuses_local_list_drift_before_push(self):
        value, _previous = self.selection_fixture()
        calls = []

        def command(argv, phase, timeout=180):
            calls.append(argv)
            index = copy.deepcopy(self.index)
            if argv[-1] == REPOSITORY + ':manifest-123':
                index['manifests'].pop()
            return json.dumps(index)

        with patch.dict(MODULE['pin'].__globals__, command=command), self.assertRaises(ValueError):
            self.pin(value)
        self.assertFalse(any('push' in call for call in calls))
        self.assertFalse(self.output.exists())

    def test_pin_wrong_digest_or_failed_push_emits_no_receipt(self):
        value, _previous = self.selection_fixture()
        for digest in ('sha256:' + 'a' * 64, '', 'private-error', 'sha256:' + 'f' * 64 + '\nextra'):
            self.pin_calls, self.pin_digest = [], digest
            with patch.dict(MODULE['pin'].__globals__, command=self.pin_command), self.assertRaises(ValueError):
                self.pin(value)
            self.assertFalse(self.output.exists())
        self.pin_calls, self.pin_digest = [], 'sha256:' + 'f' * 64

        def failing(argv, phase, timeout=180):
            if 'push' in argv:
                raise subprocess.CalledProcessError(37, argv, stderr='private-error')
            return self.pin_command(argv, phase, timeout)

        with patch.dict(MODULE['pin'].__globals__, command=failing), self.assertRaises(subprocess.CalledProcessError):
            self.pin(value)
        self.assertFalse(self.output.exists())

    def test_pin_requires_successful_tag_readback(self):
        value, _previous = self.selection_fixture()
        self.pin_calls, self.pin_digest = [], 'sha256:' + 'f' * 64

        def command(argv, phase, timeout=180):
            if argv[:3] == ['podman', 'manifest', 'inspect'] and argv[-1].startswith('registry.eyrie/nest/config/main:compiler-'):
                return '{}'
            return self.pin_command(argv, phase, timeout)

        with patch.dict(MODULE['pin'].__globals__, command=command), self.assertRaises(ValueError):
            self.pin(value)
        self.assertFalse(self.output.exists())

    def test_ci_requires_pin_before_environment_can_consume_candidate(self):
        ci = (ROOT / '.gitlab-ci.yml').read_text()
        deploy = ci.split("'Deploy image':", 1)[1].split("'Check executor bootstrap selection':", 1)[0]
        self.assertLess(deploy.index('nest-compiler-candidate.py candidate'), deploy.index('nest-compiler-candidate.py pin'))
        self.assertIn('compiler-candidates/image-pin.json', deploy)
        self.assertIn('[ "$EXECUTOR_ONLY" != "true" ]; then python3 scripts/nest-compiler-candidate.py pin', deploy)
        environment = ci.split("'Deploy environment':", 1)[1].split("'Deploy image':", 1)[0]
        self.assertIn("- job: 'Deploy image'", environment)
        self.assertIn('artifacts: true', environment)

    def selection_fixture(self):
        value = dict(schema=1, kind='nest_openvox_compiler_candidate', source=SHA, pipeline=123,
                     current=dict(image=INDEX, expected=copy.deepcopy(EXPECTED)), members=copy.deepcopy(self.rows),
                     deployment_authorized=False, retention_complete=False, compiler_attestation=False)
        older = dict(image=INDEX.replace('f' * 64, 'a' * 64),
                     expected=dict(EXPECTED, source='b' * 40, code_id='sha256:' + 'b' * 64))
        oldest = dict(image=INDEX.replace('f' * 64, 'c' * 64),
                      expected=dict(EXPECTED, source='c' * 40, code_id='sha256:' + 'c' * 64))
        previous = dict(schema=1, current=older, retained=[oldest])
        return value, previous

    def select(self, value, previous):
        return MODULE['selection'](self.save('input-candidate.json', value), self.save('previous.json', previous), self.output)

    def test_selection_retains_every_prior_identity_without_mutating_input_or_deploying(self):
        value, previous = self.selection_fixture()
        original = copy.deepcopy(previous)
        with patch.object(MODULE['subprocess'], 'run') as execute, patch.dict(os.environ, clear=True):
            execute.return_value.stdout = json.dumps(self.index)
            result = self.select(value, previous)
        self.assertEqual(result, dict(schema=1, current=value['current'], retained=[previous['current'], *previous['retained']]))
        self.assertEqual(json.loads(self.output.read_bytes()), result)
        self.assertEqual(previous, original)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0], ['podman', 'manifest', 'inspect', INDEX])

    def test_selection_repeat_and_rollback_preserve_all_other_identities(self):
        value, previous = self.selection_fixture()
        prior_current = copy.deepcopy(previous['current'])
        for where in ('current', 'retained'):
            with self.subTest(where=where):
                if where == 'current':
                    previous['current'] = value['current']
                else:
                    previous['current'] = prior_current
                    previous['retained'].append(value['current'])
                with patch.object(MODULE['subprocess'], 'run') as execute:
                    execute.return_value.stdout = json.dumps(self.index)
                    result = self.select(value, previous)
                self.assertNotIn(value['current'], result['retained'])
                for item in [previous['current'], *previous['retained']]:
                    self.assertIn(item, [result['current'], *result['retained']])
                self.output.unlink()

    def test_selection_refuses_legacy_absent_empty_and_duplicate_previous_before_registry(self):
        value, previous = self.selection_fixture()
        cases = [None, {}, dict(schema=1, current=None, retained=[]), dict(previous, schema=True),
                 dict(previous, retained=[previous['current']]), dict(previous, retained='unknown'),
                 dict(previous, extra='unexpected')]
        for prior in cases:
            with self.subTest(prior=prior), patch.object(MODULE['subprocess'], 'run') as execute:
                with self.assertRaises(ValueError):
                    self.select(value, prior)
                execute.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_selection_rejects_same_code_id_with_changed_source_and_mutable_prior_images(self):
        value, previous = self.selection_fixture()
        for mutate in (lambda prior: prior['current']['expected'].update(code_id=EXPECTED['code_id']),
                       lambda prior: prior['retained'][0].update(image='registry.eyrie/nest/config/main:latest'),
                       lambda prior: prior['current']['expected'].update(schema=True)):
            prior = copy.deepcopy(previous)
            mutate(prior)
            with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
                self.select(value, prior)
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_selection_refuses_tampered_candidate_schema_flags_and_member_identity_before_registry(self):
        value, previous = self.selection_fixture()
        for mutate in (lambda item: item.update(schema=True), lambda item: item.update(pipeline=True),
                       lambda item: item.update(source='b' * 40), lambda item: item.update(deployment_authorized=True),
                       lambda item: item.update(retention_complete=True), lambda item: item.update(compiler_attestation=0),
                       lambda item: item['members'].pop(), lambda item: item['members'].reverse(),
                       lambda item: item['members'][1]['executor'].update(job=101),
                       lambda item: item['members'][1]['executor'].update(pipeline=124),
                       lambda item: item['members'][1]['executor']['inputs'].update(puppetfile_digest='sha256:' + 'd' * 64),
                       lambda item: item['current'].update(image='registry.eyrie/nest/config/main:latest')):
            bad = copy.deepcopy(value)
            mutate(bad)
            with patch.object(MODULE['subprocess'], 'run') as execute, self.assertRaises(ValueError):
                self.select(bad, previous)
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_selection_reopens_index_and_refuses_wrong_platform_or_digest(self):
        value, previous = self.selection_fixture()
        for mutate in (lambda index: index['manifests'].pop(),
                       lambda index: index['manifests'][0].update(digest='sha256:' + '0' * 64),
                       lambda index: index['manifests'][0]['platform'].update(os='windows'),
                       lambda index: index['manifests'][1]['platform'].update(architecture='amd64'),
                       lambda index: index['manifests'][0].update(size=True),
                       lambda index: index['manifests'][0]['platform'].update(variant='v8')):
            bad = copy.deepcopy(self.index)
            mutate(bad)
            with patch.object(MODULE['subprocess'], 'run') as execute:
                execute.return_value.stdout = json.dumps(bad)
                with self.assertRaises(ValueError):
                    self.select(value, previous)
            self.assertFalse(self.output.exists())

    def test_selection_never_replaces_existing_output(self):
        value, previous = self.selection_fixture()
        self.output.write_text('prior accepted selection')
        with patch.object(MODULE['subprocess'], 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            with self.assertRaises(FileExistsError):
                self.select(value, previous)
        self.assertEqual(self.output.read_text(), 'prior accepted selection')


if __name__ == '__main__':
    unittest.main()
