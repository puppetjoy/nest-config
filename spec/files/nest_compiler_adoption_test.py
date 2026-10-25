"""Read-only compiler adoption reconciliation; inert inputs and fake registry only."""
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
SCRIPT = ROOT / 'scripts/nest-compiler-adoption.py'
MODULE = runpy.run_path(str(SCRIPT))
FIXTURE = runpy.run_path(str(ROOT / 'spec/files/nest_compiler_candidate_test.py'))
UUID = '11111111-1111-4111-8111-111111111111'


class CompilerAdoptionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'proposal.json'
        self.expected = copy.deepcopy(FIXTURE['EXPECTED'])
        self.rows = [dict(schema=1, executor=FIXTURE['member'](cpu, number), expected=copy.deepcopy(self.expected))
                     for number, cpu in enumerate(MODULE['CANDIDATE']['CPUS'], 1)]
        self.candidate = dict(schema=1, kind='nest_openvox_compiler_candidate', source=FIXTURE['SHA'], pipeline=123,
                              current=dict(image=FIXTURE['INDEX'], expected=self.expected), members=self.rows,
                              deployment_authorized=False, retention_complete=False, compiler_attestation=False)
        self.client = dict(hostname='fixture', certname='fixture.nest', server='puppet.eyrie')
        self.scope = dict(schema=1, clients=[self.client])
        self.cache = dict(configuration_version='b' * 40, code_id=None, catalog_uuid=UUID, cache_sha256='c' * 64)
        self.observations = [dict(schema=1, kind='nest_compiler_catalog_cache', **self.client, boot_id=UUID,
                                  observed_at=1000, environment='main', cache=self.cache, read_only=True,
                                  catalog_applied=False, acceptance_recorded=False)]
        self.releases = []
        self.index = dict(schemaVersion=2, mediaType='application/vnd.oci.image.index.v1+json', manifests=[
            dict(mediaType='application/vnd.oci.image.manifest.v1+json', size=1000,
                 digest=row['executor']['image'].split('@')[1],
                 platform=dict(os='linux', architecture=MODULE['CANDIDATE']['CPUS'][row['executor']['cpu']])) for row in self.rows])

    def paths(self):
        paths = []
        for name, value in [('candidate', self.candidate), ('scope', self.scope),
                            ('observations', self.observations), ('releases', self.releases)]:
            path = self.root / (name + '.json')
            path.write_text(json.dumps(value))
            paths.append(path)
        return paths

    def propose(self):
        return MODULE['propose'](*self.paths(), self.output, now=1000)

    def test_first_adoption_reconciles_present_null_without_inventing_previous_selection_or_history(self):
        with patch.object(subprocess, 'run') as execute, patch.dict(os.environ, clear=True):
            execute.return_value.stdout = json.dumps(self.index)
            result = self.propose()
        self.assertEqual(result, json.loads(self.output.read_bytes()))
        self.assertEqual(result['legacy_null_code_id_clients'], ['fixture.nest'])
        self.assertEqual(result['selection'], dict(schema=1, current=self.candidate['current'], retained=[]))
        self.assertTrue(result['scope_cache_reconciled'])
        for key in ('global_cache_coverage', 'legacy_historical_content_bound', 'deployment_authorized', 'retention_complete', 'compiler_attestation'):
            self.assertIs(result[key], False)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0], ['podman', 'manifest', 'inspect', FIXTURE['INDEX']])
        self.assertNotIn('cache_sha256', json.dumps(result))

    def test_retains_every_known_release_including_unobserved_identities(self):
        for char in ('b', 'c'):
            self.releases.append(dict(image=FIXTURE['INDEX'].replace('f' * 64, char * 64),
                                      expected=dict(self.expected, source=char * 40, code_id='sha256:' + char * 64)))
        self.cache['code_id'] = self.releases[0]['expected']['code_id']
        with patch.object(subprocess, 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            result = self.propose()
        self.assertEqual(result['selection']['retained'], self.releases)
        self.assertEqual(result['legacy_null_code_id_clients'], [])

    def test_darwin_schema_preserves_native_boot_identity_without_relaxing_linux(self):
        row = self.observations[0]
        native = '5F573720-AD7D-4CC8-90CB-4FB2520C257A'
        row.update(schema=2, platform='darwin', boot_source='kern.bootsessionuuid', boot_id=native)
        with patch.object(subprocess, 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            result = self.propose()
        self.assertTrue(result['scope_cache_reconciled'])
        self.assertEqual(row['boot_id'], native)
        self.assertFalse(result['global_cache_coverage'])
        self.assertFalse(result['deployment_authorized'])
        self.output.unlink()
        original = copy.deepcopy(row)
        for change in (dict(schema=1), dict(schema=3), dict(schema=True), dict(platform='windows'),
                       dict(boot_source='linux'), dict(boot_id=native.lower()), dict(boot_id=native + '\n')):
            self.observations[0] = dict(original, **change)
            with self.subTest(change=change), patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
                self.propose()
            execute.assert_not_called()
            self.assertFalse(self.output.exists())
        self.observations[0] = dict(original)
        del self.observations[0]['boot_source']
        with patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
            self.propose()
        execute.assert_not_called()

    def test_windows_schema_requires_native_boot_source_and_never_relaxes_other_platforms(self):
        row = self.observations[0]
        source = 'NtQuerySystemInformation.SystemBootEnvironmentInformation.BootIdentifier'
        row.update(schema=3, platform='windows', boot_source=source)
        with patch.object(subprocess, 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            result = self.propose()
        self.assertTrue(result['scope_cache_reconciled'])
        self.assertFalse(result['deployment_authorized'])
        self.assertFalse(result['global_cache_coverage'])
        self.output.unlink()
        for change in (dict(schema=1), dict(schema=2), dict(schema=True), dict(platform='cygwin'),
                       dict(platform='darwin'), dict(boot_source='LastBootUpTime'), dict(boot_id=UUID + '\n')):
            self.observations[0] = dict(row, **change)
            with self.subTest(change=change), patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
                self.propose()
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_legacy_abbreviations_remain_unresolved_observations_not_release_sources(self):
        for version in ('5b732030', '13c279d6', 'a' * 7, 'a' * 39):
            self.cache['configuration_version'] = version
            with self.subTest(version=version), patch.object(subprocess, 'run') as execute:
                execute.return_value.stdout = json.dumps(self.index)
                result = self.propose()
                self.assertEqual(result['legacy_null_code_id_clients'], ['fixture.nest'])
                self.assertEqual(result['selection']['current']['expected']['source'], FIXTURE['SHA'])
                self.assertFalse(result['legacy_historical_content_bound'])
                self.assertFalse(result['compiler_attestation'])
                self.assertEqual(self.cache['configuration_version'], version)
                self.assertEqual(execute.call_count, 1)
                self.output.unlink()

    def test_abbreviated_immutable_and_malformed_legacy_versions_refuse_before_registry(self):
        for identity, version in [(self.expected['code_id'], self.expected['source'][:8])] + [
                (None, version) for version in ('', 'a' * 6, 'a' * 41, 'main', '5b732030-extra', '5b732030\n', '5B732030')]:
            self.cache.update(code_id=identity, configuration_version=version)
            with self.subTest(identity=identity, version=version), patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
                self.propose()
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_candidate_identity_is_allowed_but_source_must_match(self):
        self.cache.update(code_id=self.expected['code_id'], configuration_version=self.expected['source'])
        with patch.object(subprocess, 'run') as execute:
            execute.return_value.stdout = json.dumps(self.index)
            self.propose()
        self.output.unlink()
        self.cache['configuration_version'] = 'b' * 40
        with patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
            self.propose()
        execute.assert_not_called()

    def test_missing_duplicate_foreign_stale_future_unsafe_or_unknown_cache_refuses_before_registry(self):
        original = copy.deepcopy(self.observations)
        mutations = [lambda: self.observations.clear(), lambda: self.observations.append(copy.deepcopy(self.observations[0])),
                     lambda: self.observations[0].update(certname='other'), lambda: self.observations[0].update(hostname='other'),
                     lambda: self.observations[0].update(server='other'), lambda: self.observations[0].update(schema=True),
                     lambda: self.observations[0].update(observed_at=99), lambda: self.observations[0].update(observed_at=1001),
                     lambda: self.observations[0].update(observed_at=True), lambda: self.observations[0].update(read_only=1),
                     lambda: self.observations[0].update(catalog_applied=True), lambda: self.observations[0].update(acceptance_recorded=True),
                     lambda: self.observations[0].update(boot_id='unknown'), lambda: self.observations[0].update(environment='test'),
                     lambda: self.observations[0].update(extra='private-secret'), lambda: self.observations[0]['cache'].pop('code_id'),
                     lambda: self.observations[0]['cache'].update(code_id=''),
                     lambda: self.observations[0]['cache'].update(code_id='sha256:' + 'd' * 64),
                     lambda: self.observations[0]['cache'].update(catalog_uuid='unknown'),
                     lambda: self.observations[0]['cache'].update(cache_sha256='wrong'),
                     lambda: self.observations[0]['cache'].update(configuration_version='main')]
        for number, mutate in enumerate(mutations):
            self.observations = copy.deepcopy(original)
            mutate()
            with self.subTest(case=number), patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
                self.propose()
            execute.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_empty_duplicate_or_malformed_scope_and_conflicting_known_releases_refuse(self):
        for scope in ({}, dict(schema=True, clients=[self.client]), dict(schema=1, clients=[]),
                      dict(schema=1, clients=[self.client, self.client]), dict(schema=1, clients=[dict(self.client, server='bad/server')])):
            self.scope = scope
            with patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
                self.propose()
            execute.assert_not_called()
        self.scope = dict(schema=1, clients=[self.client])
        for releases in ({}, [self.candidate['current'], self.candidate['current']],
                         [dict(image='registry.eyrie/nest/config/main:latest', expected=self.expected)],
                         [dict(image=FIXTURE['INDEX'], expected=dict(self.expected, source='b' * 40))]):
            self.releases = releases
            with patch.object(subprocess, 'run') as execute, self.assertRaises(ValueError):
                self.propose()
            execute.assert_not_called()

    def test_reopens_index_and_never_overwrites_a_prior_proposal(self):
        with patch.object(subprocess, 'run') as execute:
            execute.return_value.stdout = json.dumps(dict(self.index, manifests=[]))
            with self.assertRaises(ValueError):
                self.propose()
            self.output.write_text('previous')
            execute.return_value.stdout = json.dumps(self.index)
            with self.assertRaises(FileExistsError):
                self.propose()
        self.assertEqual(self.output.read_text(), 'previous')

    def test_real_cli_sanitizes_errors_without_native_payload_or_proposal(self):
        paths = self.paths()
        podman = self.root / 'podman'
        podman.write_text('#!/bin/sh\nprintf private-secret-native-error >&2\nexit 37\n')
        podman.chmod(0o755)
        # Current receipt time permits reaching the inert registry failure.
        import time
        self.observations[0]['observed_at'] = int(time.time())
        paths = self.paths()
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, paths), str(self.output)],
                                capture_output=True, text=True, env=dict(PATH=str(self.root) + os.pathsep + os.defpath))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('private-secret', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
