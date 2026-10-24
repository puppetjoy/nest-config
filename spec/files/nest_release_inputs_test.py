#!/usr/bin/env python3
"""Exercise real input publication and Git identity with local disposable fixtures."""

import copy
import hashlib
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
SCRIPT = ROOT / 'scripts/nest-release-inputs.py'
MODULE = runpy.run_path(str(SCRIPT))
RELEASE = MODULE['release']


class ReleaseInputsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()
        # A disposable fixture must not inherit a real pipeline's release,
        # route, graph or build selection (or its credentials). Keep only the
        # command lookup and explicitly selected temporary-storage location.
        self.env = {key: os.environ[key] for key in ('PATH', 'TMPDIR') if key in os.environ}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                        PYTHONDONTWRITEBYTECODE='1')
        (self.checkout / 'tracked').write_text('Fixture only\n')
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.git('add', '.')
        self.git('commit', '-m', 'Fixture only')
        self.sha = self.git('rev-parse', 'HEAD')
        self.env.update(RELEASE_INPUTS='true', CI_PROJECT_PATH='nest/config', CI_PROJECT_ID='3',
                        CI_COMMIT_SHA=self.sha, CI_PIPELINE_ID='901', CI_JOB_ID='902',
                        CI_PROJECT_DIR=str(self.checkout))
        for name in ('BUILD', 'EXECUTOR_ONLY', 'RELEASE_CANDIDATE', 'RELEASE_VALIDATE_ONLY'):
            self.env.pop(name, None)
        self.member = {'id': 'fixture-stage0', 'stage': 'stage0', 'project': 'nest/stage0',
                       'cpu': 'haswell', 'platform': None, 'variant': 'server', 'host': None,
                       'mode': 'refresh', 'bases': {'image': 'fixture.invalid/nest/base@sha256:' + 'b' * 64},
                       'compatibility': {}, 'identity_root': None}
        self.expected = {'schema': 1, 'kind': 'nest_release_expectations', 'release': 'fixture-only',
                         'sources': {'nest/config': self.sha, 'nest/overlay': 'a' * 40,
                                     'nest/gentoo/portage': 'b' * 40, 'nest/gentoo/haskell': 'c' * 40,
                                     'nest/stage0': 'd' * 40},
                         'executor': {'source': self.sha, 'image': 'fixture.invalid/nest/config/main@sha256:' + 'e' * 64},
                         'members': [self.member],
                         'consumers': [{'project': p, 'decision': 'defer', 'reason': 'Fixture only', 'members': []}
                                       for p in sorted(RELEASE['TOOL_CONSUMERS'])]
                         + [{'project': 'nest/stage0', 'decision': 'rebuild', 'reason': 'Fixture only',
                             'members': [self.member['id']]}]}
        self.input = self.root / 'input.json'
        self.input.write_text(json.dumps(self.expected, indent=2))

    def test_fixture_does_not_inherit_real_pipeline_selection_or_credentials(self):
        outer = dict(RELEASE_ROUTE='verify-inputs', RELEASE_INPUTS='true',
                     RELEASE_ROUTE_MEMBER='real-pipeline-member', RELEASE_GRAPH='true',
                     EXECUTOR_BOOTSTRAP='true', NEST_DAG_FIXTURE='pass', BUILD='haswell',
                     CPU='zen5', CI_JOB_TOKEN='fixture-private-token')
        fixture = ReleaseInputsTest()
        with patch.dict(os.environ, outer):
            fixture.setUp()
        try:
            for key in outer:
                if key != 'RELEASE_INPUTS':
                    self.assertNotIn(key, fixture.env)
            self.assertEqual(fixture.env['RELEASE_INPUTS'], 'true')
            self.assertEqual(fixture.env['CI_PROJECT_DIR'], str(fixture.checkout))
        finally:
            fixture.doCleanups()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.checkout), *args], env=self.env,
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def cli(self, **env):
        return subprocess.run([sys.executable, str(SCRIPT), '--expectations', str(self.input)],
                              env=dict(self.env, **env), capture_output=True, text=True)

    def stage3(self, raw=None):
        self.expected = runpy.run_path(str(ROOT / 'spec/files/nest_release_manifest_test.py'))['fixture']()[0]
        self.policy = {'schema': 1, 'kind': 'nest_release_identity_trust', 'hosts': {'fixture-host': 'a' * 64}}
        policy = self.checkout / 'data/release/trust.json'
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text(json.dumps(self.policy) if raw is None else raw)
        self.git('add', 'data/release/trust.json')
        self.git('commit', '-m', 'Fixture public trust only')
        self.sha = self.git('rev-parse', 'HEAD')
        self.env['CI_COMMIT_SHA'] = self.sha
        self.expected['sources']['nest/config'] = self.sha
        self.expected['executor']['source'] = self.sha
        self.input.write_text(json.dumps(self.expected))
        return policy

    def test_stage3_uses_source_bound_public_policy_and_retains_exact_readback(self):
        policy = self.stage3()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.input.unlink()
        policy.unlink()
        retained = self.checkout / 'release-inputs/trust.json'
        self.assertEqual(retained.read_bytes(), RELEASE['canonical'](self.policy))
        receipt = json.loads((self.checkout / 'release-inputs/receipt.json').read_bytes())
        self.assertEqual(receipt['producer']['sha'], self.sha)
        self.assertNotIn('a' * 64, result.stdout + result.stderr)

    def test_stage3_absent_or_different_host_and_CA_policy_refuse_before_publication(self):
        for hosts in ({}, {'other-host': 'a' * 64}, {'fixture-host': 'b' * 64}):
            with self.subTest(hosts=hosts):
                policy = {'schema': 1, 'kind': 'nest_release_identity_trust', 'hosts': hosts}
                self.stage3(json.dumps(policy))
                self.assertNotEqual(self.cli().returncode, 0)
                self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_stage3_policy_must_exist_at_selected_Git_source(self):
        policy = self.stage3()
        self.git('rm', 'data/release/trust.json')
        self.git('commit', '-m', 'Fixture policy absent')
        self.sha = self.git('rev-parse', 'HEAD')
        self.env['CI_COMMIT_SHA'] = self.sha
        self.expected['sources']['nest/config'] = self.sha
        self.expected['executor']['source'] = self.sha
        self.input.write_text(json.dumps(self.expected))
        # An untracked replacement is not a source-managed approved policy.
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text(json.dumps(self.policy))
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_stage3_cannot_auto_accept_CA_from_submitted_expectations(self):
        self.stage3()
        self.expected['members'][3]['identity_ca_sha256'] = 'b' * 64
        self.input.write_text(json.dumps(self.expected))
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_stage3_malformed_or_extended_policies_refuse_safely(self):
        cases = ['secret-fixture', '{"schema":1,"schema":1}', '{"schema":NaN}', 'x' * (RELEASE['LIMIT'] + 1)]
        for value in ({'schema': True, 'kind': 'nest_release_identity_trust', 'hosts': {}},
                      {'schema': 1, 'kind': 'wrong', 'hosts': {}},
                      {'schema': 1, 'kind': 'nest_release_identity_trust', 'hosts': [], 'extra': True},
                      {'schema': 1, 'kind': 'nest_release_identity_trust', 'hosts': {'fixture-host': 'a' * 64 + '\n'}},
                      {'schema': 1, 'kind': 'nest_release_identity_trust', 'hosts': {'*': 'a' * 64}}):
            cases.append(json.dumps(value))
        for raw in cases:
            with self.subTest(raw=raw[:80]):
                self.stage3(raw)
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('secret-fixture', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_stage3_trust_artifact_failed_readback_refuses(self):
        self.stage3()
        original = Path.read_bytes

        def read(path):
            return b'changed' if path.name == 'trust.json' else original(path)

        with patch.object(Path, 'read_bytes', read):
            with self.assertRaises(RELEASE['Invalid']):
                MODULE['publish'](self.input, self.env)
        self.assertNotEqual(self.cli().returncode, 0)

    def test_canonical_artifacts_reopened_after_producer_exit_and_input_removal(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.input.unlink()
        payload = (self.checkout / 'release-inputs/expectations.json').read_bytes()
        self.assertEqual(payload, RELEASE['canonical'](self.expected))
        receipt = json.loads((self.checkout / 'release-inputs/receipt.json').read_bytes())
        self.assertEqual(receipt['artifact_sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(receipt['expectations_digest'], RELEASE['digest'](self.expected))
        self.assertEqual(receipt['producer'], {'project': 'nest/config', 'sha': self.sha, 'pipeline': 901, 'job': 902})
        self.assertFalse(receipt['promotion_authorized'])
        self.assertEqual(receipt['resource_verification'], 'not_performed')
        self.assertTrue(json.loads(result.stdout)['readback_verified'])
        self.assertNotIn('Fixture only', result.stdout)
        self.assertFalse((self.checkout / 'release-inputs/provenance.json').exists())

    def test_existing_output_and_symlink_refuse_without_replacement(self):
        directory = self.checkout / 'release-inputs'
        directory.mkdir()
        prior = directory / 'expectations.json'
        prior.write_text('previous')
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(prior.read_text(), 'previous')
        prior.unlink()
        directory.rmdir()
        directory.symlink_to(self.root, target_is_directory=True)
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse((self.root / 'expectations.json').exists())

    def test_wrong_or_missing_CI_identity_and_conflicting_modes_refuse(self):
        cases = [{'RELEASE_INPUTS': value} for value in ('', 'false', 'TRUE')]
        cases += [{name: 'wrong'} for name in ('CI_PROJECT_PATH', 'CI_PROJECT_ID', 'CI_COMMIT_SHA', 'CI_PIPELINE_ID', 'CI_JOB_ID')]
        cases += [{name: 'true'} for name in ('BUILD', 'EXECUTOR_ONLY', 'RELEASE_CANDIDATE', 'RELEASE_VALIDATE_ONLY')]
        cases += [{'CI_PROJECT_DIR': '.'}, {'CI_COMMIT_SHA': 'f' * 40}]
        for case in cases:
            with self.subTest(case=case):
                self.assertNotEqual(self.cli(**case).returncode, 0)
                self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_modified_tracked_checkout_refuses(self):
        (self.checkout / 'tracked').write_text('changed')
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_other_executor_source_internally_consistent_but_not_this_CI_refuses(self):
        self.expected['sources']['nest/config'] = 'f' * 40
        self.expected['executor']['source'] = 'f' * 40
        self.input.write_text(json.dumps(self.expected))
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_missing_duplicate_or_unclassified_selection_refuses(self):
        for mutate in (lambda e: e['members'].clear(), lambda e: e['members'].append(copy.deepcopy(self.member)),
                       lambda e: e['consumers'].pop(0), lambda e: e['sources'].pop('nest/gentoo/haskell'),
                       lambda e: e['members'][0]['bases'].update(image='fixture.invalid/nest/base:latest')):
            expected = copy.deepcopy(self.expected)
            mutate(expected)
            self.input.write_text(json.dumps(expected))
            self.assertNotEqual(self.cli().returncode, 0)
            self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_malformed_duplicate_nonfinite_and_oversized_inputs_refuse_safely(self):
        for raw in ('private-secret-error', '{"schema":1,"schema":1}', '{"schema":NaN}', 'x' * (RELEASE['LIMIT'] + 1)):
            self.input.write_text(raw)
            result = self.cli()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('private-secret-error', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_input_symlink_refuses(self):
        link = self.root / 'link.json'
        link.symlink_to(self.input)
        self.input = link
        self.assertNotEqual(self.cli().returncode, 0)

    def test_failed_fsync_and_changed_readback_refuse(self):
        with patch('os.fsync', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                MODULE['publish'](self.input, self.env)
        # Failure does not permit replacement/replay in the same job directory.
        self.assertNotEqual(self.cli().returncode, 0)

    def test_changed_artifact_readback_refuses(self):
        original = Path.read_bytes

        def read(path):
            data = original(path)
            return b'changed' if path.name == 'receipt.json' else data

        with patch.object(Path, 'read_bytes', read):
            with self.assertRaises(RELEASE['Invalid']):
                MODULE['publish'](self.input, self.env)
        self.assertNotEqual(self.cli().returncode, 0)


    def native(self):
        fixture = runpy.run_path(str(ROOT / 'spec/files/nest_release_discover_test.py'))
        api = fixture['NativeGitLab']()
        old = api.expected['sources']['nest/config']

        def replace(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    value[key] = replace(child)
            elif isinstance(value, list):
                value[:] = [replace(child) for child in value]
            elif value == old:
                return self.sha
            return value

        for value in api.__dict__.values():
            replace(value)
        api.result['expectations_digest'] = RELEASE['digest'](api.expected)
        self.input.write_bytes(RELEASE['canonical'](api.request))
        return api, fixture['D']

    def test_native_discovery_freezes_actual_predecessor_and_retains_provenance(self):
        api, _ = self.native()
        receipt = MODULE['publish'](self.input, self.env, discovery=True, api=api)
        self.input.unlink()
        base = self.checkout / 'release-inputs'
        frozen = RELEASE['load'](base / 'expectations.json')
        self.assertEqual(frozen['members'][0]['bases'], api.result['output']['artifacts'])
        self.assertEqual(receipt['artifact_sha256'], hashlib.sha256((base / 'expectations.json').read_bytes()).hexdigest())
        provenance = (base / 'discovery.json').read_bytes()
        sidecar = RELEASE['load'](base / 'provenance.json')
        self.assertEqual(sidecar['base_discovery']['artifact_sha256'], hashlib.sha256(provenance).hexdigest())
        self.assertEqual(sidecar['input_receipt_sha256'], hashlib.sha256((base / 'receipt.json').read_bytes()).hexdigest())
        self.assertNotIn('base_discovery', receipt)
        self.assertEqual(json.loads(provenance)['expectations'], frozen)
        self.assertEqual(RELEASE['load'](base / 'receipt.json'), receipt)
        self.assertFalse(receipt['promotion_authorized'])
        self.assertEqual(receipt['resource_verification'], 'not_performed')

    def test_native_failed_or_changed_predecessor_refuses_before_output(self):
        for kind in ('failed', 'erased', 'changed'):
            api, _ = self.native()
            if kind == 'failed': api.child['status'] = 'failed'
            if kind == 'erased': api.jobs[('nest/stage0', 101)]['erased_at'] = 'fixture'
            if kind == 'changed': api.after_result = lambda a: a.bridge.update(id=701)
            with self.assertRaises(ValueError):
                MODULE['publish'](self.input, self.env, discovery=True, api=api)
            self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_native_wrong_source_and_dirty_checkout_refuse_before_network(self):
        for kind in ('source', 'dirty'):
            api, _ = self.native()
            if kind == 'source':
                api.request['expectations']['sources']['nest/config'] = 'f' * 40
                api.request['expectations']['executor']['source'] = 'f' * 40
                self.input.write_bytes(RELEASE['canonical'](api.request))
            else:
                (self.checkout / 'tracked').write_text('modified')
            with self.assertRaises(ValueError):
                MODULE['publish'](self.input, self.env, discovery=True, api=api)
            self.assertEqual(api.native_reads, [])
            self.assertFalse((self.checkout / 'release-inputs').exists())

    def test_ci_selection_requires_exactly_one_file_and_preserves_static_mode(self):
        cmd = [sys.executable, str(SCRIPT), '--ci']
        for selection in ({}, {'RELEASE_EXPECTATIONS_FILE': str(self.input), 'RELEASE_DISCOVERY_FILE': str(self.input)}):
            env = dict(self.env)
            env.pop('RELEASE_EXPECTATIONS_FILE', None)
            env.pop('RELEASE_DISCOVERY_FILE', None)
            env.update(selection)
            result = subprocess.run(cmd, env=env, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((self.checkout / 'release-inputs').exists())
        env['RELEASE_DISCOVERY_FILE'] = ''
        result = subprocess.run(cmd, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_native_ci_cli_reopens_actual_frozen_bytes_after_exit(self):
        api, native = self.native()
        fixture = runpy.run_path(str(ROOT / 'spec/files/nest_release_bind_test.py'))
        fixture['digest_results'](api.artifacts)
        expected = native['discover'](api.request, api)
        replies = {path: api.get(path) for path in set(api.native_reads)}
        fake = self.root / 'glab'
        fixture['fake_glab'](fake, replies)
        env = dict(self.env, PATH=str(self.root) + os.pathsep + self.env['PATH'],
                   RELEASE_EXPECTATIONS_FILE='', RELEASE_DISCOVERY_FILE=str(self.input))
        result = subprocess.run([sys.executable, str(SCRIPT), '--ci'], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.input.unlink()
        base = self.checkout / 'release-inputs'
        self.assertEqual(RELEASE['load'](base / 'expectations.json'), expected['expectations'])
        self.assertEqual(RELEASE['load'](base / 'discovery.json'), expected)
        self.assertTrue(json.loads(result.stdout)['readback_verified'])

    def test_native_failed_provenance_readback_refuses(self):
        api, _ = self.native()
        original = Path.read_bytes

        def read(path):
            return b'changed' if path.name == 'provenance.json' else original(path)

        with patch.object(Path, 'read_bytes', read):
            with self.assertRaises(ValueError):
                MODULE['publish'](self.input, self.env, discovery=True, api=api)

    def test_native_failed_discovery_readback_still_refuses(self):
        api, _ = self.native()
        original = Path.read_bytes

        def read(path):
            return b'changed' if path.name == 'discovery.json' else original(path)

        with patch.object(Path, 'read_bytes', read):
            with self.assertRaises(ValueError):
                MODULE['publish'](self.input, self.env, discovery=True, api=api)


if __name__ == '__main__':
    unittest.main()
