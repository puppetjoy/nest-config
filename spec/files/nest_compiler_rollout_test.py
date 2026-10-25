"""Additive compiler CI handoff and failure tests; no cluster mutation."""
import copy
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(ROOT / 'scripts/nest-compiler-rollout.py'))
FIXTURE = runpy.run_path(str(ROOT / 'spec/files/nest_compiler_candidate_test.py'))
SHA, INDEX, EXPECTED = FIXTURE['SHA'], FIXTURE['INDEX'], FIXTURE['EXPECTED']
CURRENT = dict(image=INDEX, expected=EXPECTED)
OLD = dict(image=INDEX.replace('f' * 64, '9' * 64), expected=dict(EXPECTED, source='b' * 40, code_id='sha256:' + '8' * 64))
PRIOR = dict(schema=1, current=OLD, retained=[])


def deployment(value=PRIOR):
    releases = value['retained'] + [value['current']]
    inits = []
    for index, release in enumerate(releases):
        argv = ['ruby', '-e', 'inert unit fixture', json.dumps(release['expected']), 'first' if index == 0 else 'next']
        if index == len(releases) - 1:
            argv += [json.dumps([row['expected'] for row in releases]), value['current']['expected']['code_id']]
        inits.append(dict(name='compiler-snapshot-' + str(index), image=release['image'], command=argv,
                          volumeMounts=[dict(name='compiler-snapshots', mountPath='/compiler')],
                          securityContext=dict(readOnlyRootFilesystem=True)))
    mounts = [dict(name='compiler-snapshots', mountPath='/compiler', readOnly=True)]
    for path, sub in (('/docker-custom-entrypoint.d/20-compiler.sh', 'runtime/entrypoint'),):
        mounts.append(dict(name='compiler-snapshots', mountPath=path, subPath=sub, readOnly=True))
    return dict(apiVersion='apps/v1', kind='Deployment', metadata=dict(name='puppet-puppetserver', namespace='test',
                uid='fixture-deployment-uid', resourceVersion='123', generation=4),
                spec=dict(replicas=1, strategy=dict(type='Recreate'), template=dict(metadata=dict(annotations={MODULE['ANNOTATION']: json.dumps(value)}),
                    spec=dict(initContainers=inits, containers=[dict(name='puppet-puppetserver', volumeMounts=mounts),
                                                               dict(name='r10k-code', volumeMounts=[])],
                              volumes=[dict(name='compiler-snapshots', emptyDir={})]))),
                status=dict(observedGeneration=4, replicas=1, updatedReplicas=1, readyReplicas=1, availableReplicas=1))


class CompilerRolloutTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'output'
        self.candidate = dict(schema=1, kind='nest_openvox_compiler_candidate', source=SHA, pipeline=123,
                              current=CURRENT, members=[dict(schema=1, executor=FIXTURE['member'](cpu, index), expected=EXPECTED)
                                                        for index, cpu in enumerate(MODULE['CANDIDATE']['CPUS'], 1)],
                              deployment_authorized=False, retention_complete=False, compiler_attestation=False)
        self.candidate_path = self.root / 'candidate.json'
        self.candidate_path.write_text(json.dumps(self.candidate))
        self.before = deployment()
        self.selected = dict(schema=1, current=CURRENT, retained=[OLD])
        self.after = deployment(self.selected)
        self.after['metadata'].update(resourceVersion='124', generation=5)
        self.after['status']['observedGeneration'] = 5
        self.calls = []
        self.remote_checks = []
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def native(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:2] == ['git', 'ls-remote']:
            self.remote_checks.append((argv, kwargs))
            return (SHA + '\trefs/heads/main\n').encode()
        if argv[:2] == ['ruby', '-ryaml']:
            if '-rjson' in argv and 'YAML.load_stream' in argv[4]:
                return json.dumps([self.after]).encode()
            return json.dumps(dict(version=5, defaults=dict(datadir='data'), hierarchy=[], plan_hierarchy=[])).encode()
        return b''

    def run_rollout(self, deploy=False, check_only=False, reads=None):
        with patch.dict(MODULE['rollout'].__globals__, command=self.native, get_deployment=lambda _ns: next(reads) if reads else self.before), \
                patch.dict(MODULE['CANDIDATE'], verify_index=lambda *_args: None):
            return MODULE['rollout'](self.candidate_path, 'test', self.output, deploy, check_only)

    def test_readonly_check_reopens_index_and_retained_images_without_files_or_helm(self):
        value = self.run_rollout(check_only=True)
        self.assertEqual(value['selection'], self.selected)
        self.assertFalse(value['deployed'])
        self.assertFalse(self.output.exists())
        self.assertEqual([args[0] for args in self.calls], ['git', 'podman'])
        self.assertEqual(self.calls[-1], ['podman', 'manifest', 'inspect', OLD['image']])
        self.assertEqual(self.remote_checks, [(['git', 'ls-remote', '--exit-code', MODULE['SOURCE_REPOSITORY'], 'refs/heads/main'], {'cwd': ROOT.parent})])

    def test_render_uses_existing_kubecm_plan_and_private_invocation_hiera_only(self):
        result = self.run_rollout()
        self.assertFalse(result['deployed'])
        self.assertFalse(result['normal_catalog_accepted'])
        self.assertEqual(json.loads((self.output / 'receipt.json').read_bytes()), result)
        self.assertEqual(json.loads((self.output / 'selection.json').read_bytes()), {'nest::service::puppet::compiler_release': self.selected})
        config = json.loads((self.output / 'hiera.json').read_bytes())
        self.assertEqual((self.output / config['defaults']['datadir']).resolve(), ROOT / 'data')
        self.assertEqual(config['hierarchy'][0]['path'], 'selection.json')
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        bolt = [args for args in self.calls if args[0] == 'bolt']
        self.assertEqual(len(bolt), 1)
        self.assertEqual(bolt[0][1:4], ['plan', 'run', 'nest::eyrie::openvox::deploy'])
        self.assertTrue(any(arg.startswith('render_to=') for arg in bolt[0]))

    def test_deploy_requires_fresh_unchanged_predecessor_then_reopens_ready_exact_selection(self):
        result = self.run_rollout(deploy=True, reads=iter([self.before, self.before, self.after]))
        self.assertTrue(result['deployed'])
        self.assertTrue(result['rollout_ready'])
        self.assertFalse(result['compiler_attestation'])
        self.assertFalse(result['retention_complete'])
        self.assertEqual(len([args for args in self.calls if args[0] == 'bolt']), 2)
        self.assertIn(['kubectl', 'rollout', 'status', '-n', 'test', 'deployment/puppet-puppetserver', '--timeout=600s'], self.calls)

    def test_manual_mode_does_not_bypass_stale_main_refusal(self):
        with patch.dict(MODULE['rollout'].__globals__, command=lambda *_a, **_k: b'old\trefs/heads/main\n'), self.assertRaises(ValueError):
            MODULE['rollout'](self.candidate_path, 'test', self.output, True)
        self.assertFalse(self.output.exists())

    def test_cross_pipeline_or_non_main_ci_refuses_before_any_command(self):
        for env in (dict(CI='true'), dict(CI='true', CI_COMMIT_BRANCH='main', CI_DEFAULT_BRANCH='main', CI_COMMIT_SHA=SHA, CI_PIPELINE_ID='122')):
            with patch.dict(os.environ, env), self.assertRaises(ValueError):
                self.run_rollout(deploy=True)
        self.assertEqual(self.calls, [])

    def test_concurrent_write_stops_before_helm_apply_and_preserves_diagnostic_directory(self):
        changed = copy.deepcopy(self.before)
        changed['metadata']['resourceVersion'] = 'changed'
        with self.assertRaises(ValueError):
            self.run_rollout(deploy=True, reads=iter([self.before, changed]))
        self.assertEqual(len([args for args in self.calls if args[0] == 'bolt']), 1)
        self.assertTrue((self.output / 'selection.json').exists())
        self.assertFalse((self.output / 'receipt.json').exists())

    def test_wrong_render_or_readback_never_produces_success_receipt(self):
        for phase in ('render', 'readback'):
            with self.subTest(phase=phase):
                self.output = self.root / phase
                if phase == 'render':
                    self.after = deployment()
                else:
                    self.after = deployment(self.selected)
                wrong = deployment()
                with self.assertRaises(ValueError):
                    self.run_rollout(deploy=True, reads=iter([self.before, self.before, wrong]))
                self.assertFalse((self.output / 'receipt.json').exists())
                if phase == 'render':
                    self.assertEqual(len([args for args in self.calls if args[0] == 'bolt']), 1)
                self.calls.clear()

    def test_existing_output_never_adopted_or_overwritten(self):
        self.output.mkdir()
        (self.output / 'keep').write_text('diagnostic')
        with self.assertRaises(ValueError):
            self.run_rollout(deploy=True)
        self.assertEqual((self.output / 'keep').read_text(), 'diagnostic')
        self.assertFalse(any(args[0] in ('bolt', 'podman') for args in self.calls))

    def test_failed_native_apply_stops_without_rollout_or_receipt(self):
        native = self.native

        def fail(argv, **kwargs):
            if argv[0] == 'bolt' and not any(arg.startswith('render_to=') for arg in argv):
                raise ValueError('unit fixture apply failure')
            return native(argv, **kwargs)

        with patch.dict(MODULE['rollout'].__globals__, command=fail, get_deployment=lambda _ns: self.before), \
                patch.dict(MODULE['CANDIDATE'], verify_index=lambda *_args: None), self.assertRaises(ValueError):
            MODULE['rollout'](self.candidate_path, 'test', self.output, True)
        self.assertFalse(any(args[:2] == ['kubectl', 'rollout'] for args in self.calls))
        self.assertFalse((self.output / 'receipt.json').exists())

    def test_preserves_every_prior_identity_and_never_invents_historical_bytes(self):
        prior = dict(PRIOR, retained=[CURRENT])
        self.assertEqual(MODULE['successor'](self.candidate, prior), self.selected)
        bad = copy.deepcopy(prior)
        bad['retained'][0]['expected']['source'] = 'c' * 40
        with self.assertRaises(ValueError):
            MODULE['successor'](self.candidate, bad)
        with self.assertRaises(ValueError):
            MODULE['selection'](dict(PRIOR, retained=[OLD]))

    def test_missing_annotation_layout_drift_and_writable_or_shared_volume_refuse(self):
        changes = [lambda d: d['spec']['template']['metadata']['annotations'].clear(),
                   lambda d: d['spec'].update(strategy=dict(type='RollingUpdate')),
                   lambda d: d['metadata'].update(namespace='default'),
                   lambda d: d['spec']['template']['spec']['initContainers'][0].update(image='mutable:latest'),
                   lambda d: d['spec']['template']['spec']['initContainers'][0]['command'].__setitem__(3, '{}'),
                   lambda d: d['spec']['template']['spec']['containers'][0]['volumeMounts'][0].update(readOnly=False),
                   lambda d: d['spec']['template']['spec']['containers'][1]['volumeMounts'].append(dict(name='compiler-snapshots')),
                   lambda d: d['spec']['template']['spec']['volumes'][0].update(emptyDir=dict(medium='Memory'))]
        for change in changes:
            value = deployment()
            change(value)
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                MODULE['predecessor'](value, 'test')
        self.assertEqual(MODULE['predecessor'](self.before, 'test'), PRIOR)

    def test_unready_or_partially_observed_rollout_refuses(self):
        for key, number in (('observedGeneration', 3), ('readyReplicas', 0), ('updatedReplicas', 0), ('replicas', 2), ('unavailableReplicas', 1)):
            value = deployment()
            value['status'][key] = number
            with self.subTest(key=key), self.assertRaises(ValueError):
                MODULE['ready'](value)

    def test_chart_guard_preserves_ci_successors_during_manual_redeploy_or_rollback(self):
        with patch.dict(MODULE['guard_chart'].__globals__, get_deployment=lambda _ns: self.before,
                        rendered_deployment=lambda _path: self.after):
            self.assertTrue(MODULE['guard_chart']('test', self.root / 'fixture.yaml')['prior_identities_preserved'])
        # After CI has advanced, stale original Hiera cannot discard its new ID.
        with patch.dict(MODULE['guard_chart'].__globals__, get_deployment=lambda _ns: self.after,
                        rendered_deployment=lambda _path: self.before), self.assertRaises(ValueError):
            MODULE['guard_chart']('test', self.root / 'fixture.yaml')
        rollback = deployment(dict(schema=1, current=OLD, retained=[CURRENT]))
        with patch.dict(MODULE['guard_chart'].__globals__, get_deployment=lambda _ns: self.after,
                        rendered_deployment=lambda _path: rollback):
            self.assertTrue(MODULE['guard_chart']('test', self.root / 'fixture.yaml')['prior_identities_preserved'])

    def test_rendered_helm_namespace_may_be_implicit_but_live_identity_must_be_explicit(self):
        value = deployment()
        del value['metadata']['namespace']
        value['spec']['strategy']['rollingUpdate'] = None
        self.assertEqual(MODULE['predecessor'](value, 'test', live=False), PRIOR)
        with self.assertRaises(ValueError):
            MODULE['predecessor'](value, 'test')

    def test_native_failure_logs_stay_private_and_are_not_raised_in_public_error(self):
        with patch.object(MODULE['subprocess'], 'run', return_value=subprocess.CompletedProcess([], 1, b'private output', b'private error')):
            with self.assertRaisesRegex(ValueError, 'Compiler candidate unavailable'):
                MODULE['command'](['inert'], log=self.root / 'native')
        self.assertEqual((self.root / 'native.stderr').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'native.stderr').read_bytes(), b'private error')

    def test_canonical_ref_observation_works_without_linked_worktree_git_administration(self):
        checkout = self.root / 'isolated-checkout'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: /unmounted/private/repository/worktrees/fixture\n')
        local = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(local)], check=True, capture_output=True)
        ref = ['git', 'ls-remote', '--exit-code', str(local), 'refs/heads/main']
        with patch.dict(MODULE['command'].__globals__, ROOT=checkout):
            with self.assertRaises(ValueError):
                MODULE['command'](ref)
            # Missing main still refuses outside the checkout too; successful
            # empty advertisement isolates discovery from exact-ref admission.
            with self.assertRaises(ValueError):
                MODULE['command'](ref, cwd=checkout.parent)
            self.assertEqual(MODULE['command'](['git', 'ls-remote', str(local)], cwd=checkout.parent), b'')


if __name__ == '__main__':
    unittest.main()
