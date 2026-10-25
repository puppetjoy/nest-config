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


if __name__ == '__main__':
    unittest.main()
