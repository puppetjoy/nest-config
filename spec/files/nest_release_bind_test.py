#!/usr/bin/env python3
"""Offline exact-resource fixtures. No registry, builds, or production mutations."""

import copy
import base64
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BIND = runpy.run_path(str(ROOT / 'scripts/nest-release-bind.py'))
MANIFEST = runpy.run_path(str(ROOT / 'spec/files/nest_release_manifest_test.py'))
R = BIND['RELEASE']


def result_archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return stream.getvalue()


def fake_glab(path, replies):
    """Preserve binary archive replies in real subprocess fixtures."""
    encoded = {key: base64.b64encode(value).decode() for key, value in replies.items()}
    path.write_text('#!' + sys.executable + '\nimport base64,sys\nr=' + repr(encoded)
                    + '\nsys.stdout.buffer.write(base64.b64decode(r[sys.argv[-1]]))\n')
    path.chmod(0o700)


def digest_results(artifacts):
    """Use the hardened producers' exact naming and preserve the result bytes."""
    for key in list(artifacts):
        project, job, name = key
        if name.startswith('release-results/'):
            row = artifacts.pop(key)
            payload = R['canonical'](row)
            target = name[:-5] + '.sha256-' + hashlib.sha256(payload).hexdigest() + '.json'
            artifacts[(project, job, target)] = row


def receipt(expected, cpu='haswell'):
    return dict(schema=2, kind='nest_config_executor_member', project='nest/config',
                sha=expected['sources']['nest/config'], pipeline=900, job=901, cpu=cpu,
                image=expected['executor']['image'], source_verification='git_head_and_oci_revision',
                inputs=dict(schema=1, kind='nest_config_executor_inputs', source=expected['sources']['nest/config'],
                            base_image=MANIFEST['image'](99), puppetfile_digest='sha256:' + 'a' * 64,
                            modules=[dict(name=name, git_head=expected['sources']['nest/config'] if name == 'nest' else None,
                                          content_digest='sha256:' + 'b' * 64)
                                     for name in ('nest', 'stdlib', 'reboot', 'ruby_task_helper', 'private', 'kubecm')]))


class GitLabReadDiagnosticTest(unittest.TestCase):
    def get(self, path, result=None, error=None):
        stream = io.StringIO()
        with patch('subprocess.run', return_value=result, side_effect=error) as command, redirect_stderr(stream):
            with self.assertRaisesRegex(ValueError, '^GitLab read failed$'):
                BIND['GitLab']().get(path)
        diagnostic = json.loads(stream.getvalue())
        self.assertEqual(set(diagnostic), {'schema', 'kind', 'operation', 'failure'})
        self.assertEqual(diagnostic['schema'], 1)
        self.assertEqual(diagnostic['kind'], 'nest_release_gitlab_read_failure')
        self.assertNotIn('private-sentinel', stream.getvalue())
        self.assertEqual(command.call_count, 1)
        return diagnostic

    def test_failed_reads_report_only_fixed_operation_and_http_status(self):
        for suffix, operation in (('', 'project'), ('/jobs/901', 'job'),
                                  ('/jobs/901/artifacts/executor-receipts/haswell.json', 'artifact')):
            for status in (401, 403, 404, 429, 500, 502, 503, 504):
                with self.subTest(operation=operation, status=status):
                    result = subprocess.CompletedProcess([], 1, b'private-sentinel',
                                                         f'private-sentinel (HTTP {status})'.encode())
                    row = self.get('projects/nest%2Fconfig' + suffix, result=result)
                    self.assertEqual((row['operation'], row['failure']), (operation, 'http_' + str(status)))

    def test_unknown_or_ambiguous_stderr_never_becomes_public_prose(self):
        for stderr in (b'private-sentinel', b'private-sentinel HTTP 401 HTTP 403', b'HTTP 200 private-sentinel'):
            row = self.get('projects/nest%2Fconfig', result=subprocess.CompletedProcess([], 1, b'', stderr))
            self.assertEqual(row['failure'], 'command_failed')

    def test_timeout_and_unavailable_command_do_not_echo_exception_details(self):
        for error, failure in ((OSError('private-sentinel'), 'command_unavailable'),
                               (subprocess.TimeoutExpired(['private-sentinel'], 60, output=b'private-sentinel'), 'timeout')):
            row = self.get('projects/nest%2Fconfig', error=error)
            self.assertEqual(row['failure'], failure)

    def test_oversized_success_is_still_refused(self):
        row = self.get('projects/nest%2Fconfig', result=subprocess.CompletedProcess([], 0, b'x' * (R['LIMIT'] + 1), b''))
        self.assertEqual(row['failure'], 'oversized_response')

    def test_success_preserves_exact_bytes_and_has_no_diagnostic(self):
        stream = io.StringIO()
        payload = b'{"id":3,"path_with_namespace":"nest/config"}'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, payload, b'')), redirect_stderr(stream):
            self.assertEqual(BIND['GitLab']().get('projects/nest%2Fconfig'), payload)
        self.assertEqual(stream.getvalue(), '')

    def test_unsupported_path_still_refuses_before_command(self):
        with patch('subprocess.run') as command:
            with self.assertRaisesRegex(ValueError, '^unsupported GitLab read$'):
                BIND['GitLab']().get('projects/nest%2Fconfig?private-sentinel')
        command.assert_not_called()


class FakeGitLab:
    request: dict[str, Any]
    result: dict[str, Any]

    def __init__(self):
        expected, candidate = MANIFEST['fixture']()
        expected['members'] = expected['members'][:2]
        for consumer in expected['consumers']:
            if consumer['project'] not in ('nest/stage0', 'nest/stage1'):
                consumer.update(decision='defer', members=[])
        self.expected = expected
        self.executor = receipt(expected)
        output = copy.deepcopy(candidate['outputs'][0])
        self.result = dict(schema=1, kind='nest_release_member_result', release=expected['release'],
                           expectations_digest=R['digest'](expected), executor_receipt=self.executor, output=output)
        template = copy.deepcopy(expected)
        template['members'] = template['members'][1:]
        next(c for c in template['consumers'] if c['project'] == 'nest/stage0').update(decision='defer', members=[])
        self.request = dict(schema=1, kind='nest_release_base_binding', expectations=template,
                            executor_job=dict(pipeline=900, job=901),
                            producers={'upstream': dict(project='nest/stage0', pipeline=1, job=101, member='stage0',
                                                        input_pipeline=800, input_job=801,
                                                        input_sha256=hashlib.sha256(R['canonical'](expected)).hexdigest(),
                                                        result_sha256=hashlib.sha256(R['canonical'](self.result)).hexdigest())},
                            bindings=[dict(target='stage1', base=role, producer='upstream', artifact=role)
                                      for role in ('normal', 'debug')])
        self.reads = []
        self.jobs = {('nest/config', 901): self.make_job('nest/config', 900, 901, 'Build haswell'),
                     ('nest/config', 801): self.make_job('nest/config', 800, 801, 'Freeze release inputs'),
                     ('nest/stage0', 101): self.make_job('nest/stage0', 1, 101, 'Candidate haswell')}
        self.artifacts = {('nest/config', 901, 'executor-receipts/haswell.json'): self.executor,
                          ('nest/config', 801, 'release-inputs/expectations.json'): expected,
                          ('nest/stage0', 101, 'release-results/stage0.json'): self.result}
        self.mutate_after_result = None

    def make_job(self, project, pipeline, identifier, name):
        return dict(id=identifier, status='success', erased_at=None, name=name,
                    pipeline=dict(id=pipeline, project_id=3 if project == 'nest/config' else 10,
                                  sha=self.expected['sources'][project]),
                    commit=dict(id=self.expected['sources'][project]), artifacts_file=dict(filename='artifacts.zip', size=123),
                    artifacts=[dict(file_type='archive', filename='artifacts.zip', size=123, file_format='zip')])

    def get(self, path):
        self.reads.append(path)
        parts = path.split('/')
        project = parts[1].replace('%2F', '/')
        if len(parts) == 2:
            row = dict(id=3 if project == 'nest/config' else 10, path_with_namespace=project)
        elif len(parts) == 4:
            row = self.jobs[(project, int(parts[3]))]
        elif len(parts) == 5 and parts[4] == 'artifacts':
            entries = [(name, R['canonical'](row)) for (p, j, name), row in self.artifacts.items()
                       if p == project and j == int(parts[3])]
            raw = result_archive(entries)
            if self.mutate_after_result:
                self.mutate_after_result(self)
            return raw
        else:
            key = (project, int(parts[3]), '/'.join(parts[5:]))
            row = self.artifacts[key]
            if key[-1] == 'release-results/stage0.json' and self.mutate_after_result:
                self.mutate_after_result(self)
        return R['canonical'](row)

    def reseal(self):
        selector = self.request['producers']['upstream']
        selector['input_sha256'] = hashlib.sha256(R['canonical'](self.expected)).hexdigest()
        self.result['expectations_digest'] = R['digest'](self.expected)
        selector['result_sha256'] = hashlib.sha256(R['canonical'](self.result)).hexdigest()


class ReleaseBindTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitLab()

    def bind(self):
        return BIND['bind'](self.api.request, self.api)

    def test_digest_named_producer_result_preserves_binding_and_raw_hash(self):
        expected = self.bind()
        digest_results(self.api.artifacts)
        self.assertEqual(self.bind(), expected)

    def test_archive_result_selection_and_name_byte_hash_refusals(self):
        payload = R['canonical'](self.api.result)
        digest_name = 'release-results/stage0.sha256-' + hashlib.sha256(payload).hexdigest() + '.json'
        legacy = 'release-results/stage0.json'

        class Archive:
            raw: bytes

            def get(self, path):
                self.path = path
                return self.raw

        api = Archive()
        for entries in ([(digest_name, payload)], [(legacy, payload)],
                        [(digest_name, payload), ('release-results/stage0.other.json', b'{}')]):
            api.raw = result_archive(entries)
            self.assertEqual(BIND['result_bytes'](api, 'nest/stage0', 101, 'stage0'), payload)
        cases = [[], [(digest_name, payload), (legacy, payload)],
                 [(legacy, payload), (legacy, payload)],
                 [(digest_name.replace(hashlib.sha256(payload).hexdigest(), '0' * 64), payload)],
                 [(digest_name, payload + b' ')], [(digest_name.replace('.sha256-', '.sha256-zz'), payload)],
                 [('release-results/other.json', payload)], [(legacy, b'not JSON')],
                 [(legacy, payload), ('../unsafe', b'{}')],
                 [(legacy, payload), ('/absolute', b'{}')],
                 [(legacy, payload), ('release-results/../unsafe', b'{}')],
                 [(legacy, payload), ('back\\slash', b'{}')],
                 [(legacy, payload)] + [('other-' + str(i), b'') for i in range(256)],
                 [(legacy, b' ' * (R['LIMIT'] + 1))]]
        for entries in cases:
            with self.subTest(names=[name for name, _ in entries]):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    api.raw = result_archive(entries)
                with self.assertRaises(ValueError): BIND['result_bytes'](api, 'nest/stage0', 101, 'stage0')
        for raw in (b'not ZIP', b'x' * (R['LIMIT'] + 1)):
            api.raw = raw
            with self.assertRaises(ValueError): BIND['result_bytes'](api, 'nest/stage0', 101, 'stage0')

    def test_result_archive_rejects_links_and_checks_raw_not_canonical_bytes(self):
        payload = json.dumps(self.api.result, indent=2).encode() + b'\n'
        sha = hashlib.sha256(payload).hexdigest()
        name = 'release-results/stage0.sha256-' + sha + '.json'
        with patch.object(self.api, 'get', return_value=result_archive([(name, payload)])):
            self.assertEqual(BIND['result_bytes'](self.api, 'nest/stage0', 101, 'stage0', sha), payload)
            with self.assertRaises(ValueError):
                BIND['result_bytes'](self.api, 'nest/stage0', 101, 'stage0', hashlib.sha256(R['canonical'](self.api.result)).hexdigest())
        entry = zipfile.ZipInfo('release-results/stage0.json')
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        with patch.object(self.api, 'get', return_value=result_archive([(entry, payload)])):
            with self.assertRaises(ValueError): BIND['result_bytes'](self.api, 'nest/stage0', 101, 'stage0')

    def test_actual_predecessor_pair_replaces_only_selected_bases_and_reseals(self):
        before = copy.deepcopy(self.api.request)
        expected, result = self.bind()
        self.assertEqual(self.api.request, before)
        self.assertEqual(expected['members'][0]['bases'], self.api.result['output']['artifacts'])
        self.assertNotEqual(result['before_expectations_digest'], result['expectations_digest'])
        self.assertEqual(result['expectations_digest'], R['digest'](expected))
        self.assertEqual(len(result['changes']), 2)
        self.assertFalse(result['promotion_authorized'])
        self.assertEqual(result['image_compatibility_verification'], 'not_performed')
        self.assertEqual(len(self.api.reads), 15)

    def test_stage0_server_pair_seeds_stage1_workstation(self):
        self.api.request['expectations']['members'][0]['variant'] = 'workstation'
        self.bind()

    def test_job_and_artifact_identity_failures(self):
        for change in ('status', 'erased', 'pipeline', 'project', 'source', 'commit', 'archive', 'input_name', 'executor_name'):
            with self.subTest(change=change):
                self.api = FakeGitLab()
                row = self.api.jobs[('nest/stage0', 101)]
                if change == 'status': row['status'] = 'failed'
                if change == 'erased': row['erased_at'] = 'fixture-erased'
                if change == 'pipeline': row['pipeline']['id'] += 1
                if change == 'project': row['pipeline']['project_id'] = 3
                if change == 'source': row['pipeline']['sha'] = 'e' * 40
                if change == 'commit': row['commit']['id'] = 'e' * 40
                if change == 'archive': row['artifacts'][0]['size'] += 1
                if change == 'input_name': self.api.jobs[('nest/config', 801)]['name'] = 'Untrusted fixture'
                if change == 'executor_name': self.api.jobs[('nest/config', 901)]['name'] = 'Build cortex-a53'
                with self.assertRaises(ValueError): self.bind()

    def test_changed_or_moved_artifact_bytes_refuse(self):
        for field in ('input_sha256', 'result_sha256'):
            with self.subTest(field=field):
                self.api = FakeGitLab()
                self.api.request['producers']['upstream'][field] = '0' * 64
                with self.assertRaises(ValueError): self.bind()

    def test_complete_member_receipt_schema_and_binding_are_checked(self):
        for change in ('kind', 'digest', 'executor', 'job', 'member', 'debug', 'same_pair'):
            with self.subTest(change=change):
                self.api = FakeGitLab()
                row = self.api.result
                if change == 'kind': row['kind'] = 'fixture-fake-result'
                if change == 'executor': row['output']['executor']['image'] = MANIFEST['image'](88)
                if change == 'job': row['output']['producer']['job'] = 999
                if change == 'member': row['output']['member']['cpu'] = 'sifive-u74'
                if change == 'debug': del row['output']['artifacts']['debug']
                if change == 'same_pair': row['output']['artifacts']['debug'] = row['output']['artifacts']['normal']
                self.api.reseal()
                if change == 'digest':
                    row['expectations_digest'] = 'sha256:' + '0' * 64
                    self.api.request['producers']['upstream']['result_sha256'] = hashlib.sha256(R['canonical'](row)).hexdigest()
                with self.assertRaises(ValueError): self.bind()

    def test_changed_sources_and_release_never_relabel_old_builds(self):
        for target, field in (('sources', 'nest/overlay'), ('release', None)):
            self.api = FakeGitLab()
            if target == 'sources': self.api.request['expectations']['sources'][field] = 'e' * 40
            else: self.api.request['expectations']['release'] = 'other-fixture'
            with self.assertRaises(ValueError): self.bind()

    def test_status_change_during_acquisition_refuses(self):
        self.api.mutate_after_result = lambda api: api.jobs[('nest/stage0', 101)].update(status='failed')
        with self.assertRaises(ValueError): self.bind()

    def test_partial_duplicate_unknown_and_mixed_pair_binding_refuse(self):
        for change in ('partial', 'duplicate', 'unknown', 'mixed', 'unused', 'root', 'decision', 'bool'):
            with self.subTest(change=change):
                self.api = FakeGitLab()
                request = self.api.request
                if change == 'partial': request['bindings'].pop()
                if change == 'duplicate': request['bindings'].append(copy.deepcopy(request['bindings'][0]))
                if change == 'unknown': request['bindings'][0]['target'] = 'no-member'
                if change == 'mixed':
                    request['producers']['other'] = copy.deepcopy(request['producers']['upstream'])
                    request['bindings'][1]['producer'] = 'other'
                if change == 'unused': request['producers']['other'] = copy.deepcopy(request['producers']['upstream'])
                if change == 'root': request['bindings'][0]['artifact'] = 'root'
                if change == 'decision': next(c for c in request['expectations']['consumers'] if c['project'] == 'nest/stage1')['decision'] = 'reuse'
                if change == 'bool': request['executor_job']['job'] = True
                with self.assertRaises(ValueError): self.bind()

    def test_architecture_group_and_executor_receipt_refuse(self):
        member = copy.deepcopy(self.api.request['expectations']['members'][0])
        member.update(id='arm-stage1', cpu='cortex-a53')
        self.api.request['expectations']['members'].append(member)
        next(c for c in self.api.request['expectations']['consumers'] if c['project'] == 'nest/stage1')['members'].append(member['id'])
        with self.assertRaises(ValueError): self.bind()
        self.api = FakeGitLab()
        self.api.executor['cpu'] = 'cortex-a53'
        with self.assertRaises(ValueError): self.bind()

    def test_recipe_edges_preserve_debug_cpu_variant_platform_and_boot_policy(self):
        expected, _ = MANIFEST['fixture']()
        stage0, stage1, stage2, stage3, tool = expected['members']
        valid = [(stage1, 'normal', stage0, 'normal'), (stage1, 'debug', stage0, 'debug'),
                 (stage2, 'image', stage1, 'debug'), (stage3, 'image', stage2, 'image'),
                 (tool, 'image', stage1, 'normal')]
        for target, base, source, role in valid:
            BIND['compatible'](target, base, source, role)
            for field, value in (('cpu', 'sifive-u74'), ('variant', 'mobile')):
                bad = dict(source, **{field: value})
                with self.assertRaises(ValueError): BIND['compatible'](target, base, bad, role)
        with self.assertRaises(ValueError): BIND['compatible'](stage2, 'image', stage1, 'normal')
        with self.assertRaises(ValueError): BIND['compatible'](stage3, 'image', dict(stage2, platform='other'), 'image')
        with self.assertRaises(ValueError): BIND['compatible'](stage3, 'image', dict(stage2, compatibility=dict(stage2['compatibility'], firmware='other')), 'image')
        firefox = dict(tool, project='nest/tools/firefox', cpu='zen5', variant='workstation')
        BIND['compatible'](firefox, 'image', dict(stage1, variant='workstation'), 'normal')
        with self.assertRaises(ValueError): BIND['compatible'](dict(firefox, project='nest/tools/camofox'), 'image', dict(stage1, variant='workstation'), 'normal')

    def test_content_addressed_package_survives_input_removal_and_refuses_collision(self):
        expected, receipt_result = self.bind()
        package = dict(schema=1, kind='nest_release_bound_inputs', expectations=expected, binding=receipt_result)
        with tempfile.TemporaryDirectory() as directory:
            payload = R['canonical'](package)
            path = Path(R['retain'](directory, payload))
            self.api.reads.clear()
            self.assertEqual(R['load'](path), package)
            self.assertEqual(R['retain'](directory, payload), str(path))
            path.write_bytes(b'fixture-conflict')
            with self.assertRaises(ValueError): R['retain'](directory, payload)

    def test_glab_adapter_allows_only_exact_known_resource_paths_and_sanitizes_errors(self):
        api = BIND['GitLab']()
        with patch('subprocess.run') as run:
            for path in ('https://evil.example', 'projects/nest%2Fconfig/jobs/latest',
                         'projects/nest%2Fconfig/jobs/1/trace', 'projects/nest%2Fconfig/jobs/1/artifacts/../../secret'):
                with self.assertRaises(ValueError): api.get(path)
            run.assert_not_called()
            run.return_value.returncode = 1
            run.return_value.stderr = b'fixture-private-token'
            with self.assertRaisesRegex(ValueError, '^GitLab read failed$'):
                api.get('projects/nest%2Fconfig/jobs/1')

    def test_real_cli_malformed_input_has_no_network_write_or_private_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.json'
            source.write_text('{"fixture-private-token":1}')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/nest-release-bind.py'), '--binding', str(source)],
                                    capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), check=False)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(b'fixture-private-token', result.stderr + result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_real_cli_success_retains_consumable_expectations_and_provenance_package(self):
        digest_results(self.api.artifacts)
        expected, provenance = self.bind()
        replies = {path: self.api.get(path) for path in set(self.api.reads)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_bin = root / 'bin'
            fixture_bin.mkdir()
            fake = fixture_bin / 'glab'
            fake_glab(fake, replies)
            reply_file = root / 'replies.json'
            reply_file.write_text(json.dumps({key: base64.b64encode(value).decode() for key, value in replies.items()}))
            source = root / 'binding.json'
            source.write_bytes(R['canonical'](self.api.request))
            output = root / 'output'
            output.mkdir()
            command = [sys.executable, str(ROOT / 'scripts/nest-release-bind.py'), '--binding', str(source),
                       '--output-dir', str(output)]
            env = dict(os.environ, PATH=str(fixture_bin) + os.pathsep + os.environ['PATH'],
                       FIXTURE_REPLIES=str(reply_file), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run(command, env=env, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report['readback_verified'])
            self.assertEqual(R['load'](report['expectations_path']), expected)
            self.assertEqual(R['load'](report['path'])['binding'], provenance)
            source.unlink()
            reply_file.unlink()
            self.assertEqual(R['load'](report['expectations_path']), expected)
            self.assertEqual(len(list(output.iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
