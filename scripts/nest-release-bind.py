#!/usr/bin/env python3
"""Bind descendant base inputs to exact successful GitLab member results.

Read-only by default. Does not build, trigger, promote, or authorize a release.
"""

import argparse
import copy
import hashlib
import io
import json
import os

from pathlib import Path
import re
import runpy
import subprocess
import sys
import stat
import zipfile
import zlib
from typing import Any, NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
RELEASE = runpy.run_path(str(ROOT / 'scripts/nest-release-manifest.py'))
EXECUTOR = runpy.run_path(str(ROOT / 'bin/ci-executor-receipt'))
require = RELEASE['require']
fields = RELEASE['fields']
match = RELEASE['match']
HOST = 'gitlab.joyfullee.me'
CPUS = {'haswell': 'haswell', 'zen5': 'haswell', 'arm1176': 'cortex-a53',
        'cortex-a8': 'cortex-a53', 'cortex-a53': 'cortex-a53', 'cortex-a72': 'cortex-a53',
        'sifive-u74': 'sifive-u74', 'thead-c920': 'sifive-u74'}
TOOLS = {'nest/tools/' + name for name in ('bolt', 'pdk', 'agent', 'firefox', 'camofox', 'llama.cpp')}
PROJECTS = {'nest/config', 'nest/stage0', 'nest/stage1', 'nest/stage2', 'nest/stage3'} | TOOLS


def decode(raw):
    require(len(raw) <= RELEASE['LIMIT'], 'oversized GitLab response')
    return json.loads(raw, object_pairs_hook=RELEASE['unique_object'], parse_int=RELEASE['json_integer'],
                      parse_constant=lambda _: require(False, 'nonfinite JSON'))


class GitLab:
    """Use glab locally and the ephemeral job token in CI; never change identity on failure."""

    def producer_job(self, base, pipeline, identifier):
        if not os.environ.get('CI_JOB_TOKEN'):
            return decode(self.get(base + '/jobs/' + str(identifier)))
        # READ_JOBS supports pipeline job lists, not arbitrary single-job reads.
        # One bounded complete page is sufficient for these member pipelines.
        rows = decode(self.get(base + '/pipelines/' + str(pipeline) + '/jobs?per_page=100&include_retried=true'))
        require(type(rows) is list and len(rows) < 100, 'incomplete producer job inventory')
        selected = [row for row in rows if type(row) is dict and type(row.get('id')) is int
                    and row['id'] == identifier]
        require(len(selected) == 1, 'missing or ambiguous producer job')
        return selected[0]

    def get(self, path):
        require(re.fullmatch(r'projects/nest(?:%2F[a-z0-9._-]+)+(?:/jobs/[1-9][0-9]{0,19}'
                             r'(?:/artifacts(?:/(?:release-inputs/expectations\.json|'
                             r'executor-receipts/(?:haswell|cortex-a53|sifive-u74)\.json|'
                             r'release-results/[a-z0-9][a-z0-9._-]{0,127}\.json))?)?)?', path) is not None
                or re.fullmatch(r'projects/nest(?:%2F[a-z0-9._-]+)+/pipelines/[1-9][0-9]{0,19}'
                                r'/jobs\?per_page=100&include_retried=true', path) is not None,
                'unsupported GitLab read')
        operation = 'artifact' if '/artifacts' in path else 'job' if '/jobs' in path else 'project'
        return self._read(path, operation)

    def _read(self, path, operation):
        """Read an already allowlisted path with the same credential boundary."""

        def refuse(failure) -> NoReturn:
            # Never print the path, response body, command stderr or credentials.
            # These fixed classifications diagnose native job-token admission
            # without changing resource checks or substituting another identity.
            print(json.dumps({'schema': 1, 'kind': 'nest_release_gitlab_read_failure',
                              'operation': operation, 'failure': failure}, sort_keys=True), file=sys.stderr)
            raise ValueError('GitLab read failed')

        if os.environ.get('CI_JOB_TOKEN'):
            # Public project identity is read explicitly without authentication:
            # the job token has no project-details endpoint. This is not a retry
            # or fallback. All job/artifact requests use only this job's token.
            # Never let redirects send a token to storage or another origin.
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None

            headers = {} if operation == 'project' else {'JOB-TOKEN': os.environ['CI_JOB_TOKEN']}
            request = Request('https://' + HOST + '/api/v4/' + path, headers=headers, method='GET')
            try:
                with build_opener(NoRedirect).open(request, timeout=60) as response:
                    raw = response.read(RELEASE['LIMIT'] + 1)
            except HTTPError as error:
                refuse('http_' + str(error.code) if error.code in (401, 403, 404, 429, 500, 502, 503, 504)
                       else 'http_refused')
            except TimeoutError:
                refuse('timeout')
            except (OSError, URLError):
                refuse('transport_failed')
            if len(raw) > RELEASE['LIMIT']:
                refuse('oversized_response')
            return raw

        try:
            result = subprocess.run(['glab', 'api', '--hostname', HOST, path], capture_output=True,
                                    timeout=60, check=False)
        except subprocess.TimeoutExpired:
            refuse('timeout')
        except OSError:
            refuse('command_unavailable')
        if result.returncode != 0:
            # glab emits HTTP status in its diagnostic, but may also echo an
            # arbitrary server body. Retain only one recognized status token.
            statuses = set(re.findall(rb'\bHTTP (401|403|404|429|500|502|503|504)\b', result.stderr))
            failure = 'http_' + next(iter(statuses)).decode('ascii') if len(statuses) == 1 else 'command_failed'
            refuse(failure)
        if len(result.stdout) > RELEASE['LIMIT']:
            refuse('oversized_response')
        return result.stdout


def prefix(project):
    require(project in PROJECTS, 'unsupported producer project')
    return 'projects/' + project.replace('/', '%2F')


def positive(value):
    require(type(value) is int and 0 < value < 10 ** 20, 'invalid numeric identity')


def job(api, project, pipeline, identifier, source):
    for number in (pipeline, identifier):
        positive(number)
    match(source, RELEASE['SHA'], 'job source')
    base = prefix(project)
    repository = decode(api.get(base))
    require(repository['path_with_namespace'] == project, 'wrong GitLab repository')
    positive(repository['id'])
    row = (api.producer_job(base, pipeline, identifier) if hasattr(api, 'producer_job')
           else decode(api.get(base + '/jobs/' + str(identifier))))
    require(type(row['id']) is int and row['id'] == identifier and row['status'] == 'success'
            and row.get('erased_at') is None, 'producer job is unavailable or unsuccessful')
    observed = row['pipeline']
    require(type(observed['id']) is int and observed['id'] == pipeline
            and type(observed['project_id']) is int and observed['project_id'] == repository['id']
            and observed['sha'] == source and row['commit']['id'] == source, 'producer job identity mismatch')
    archive = row['artifacts_file']
    require(archive['filename'] == 'artifacts.zip', 'producer artifact missing')
    positive(archive['size'])
    archives = [a for a in row['artifacts'] if a.get('file_type') == 'archive']
    require(len(archives) == 1 and archives[0]['filename'] == 'artifacts.zip'
            and archives[0]['size'] == archive['size'] and archives[0]['file_format'] == 'zip',
            'producer artifact identity mismatch')
    # Ignore volatile runner/user/duration fields; retain only the resource identity.
    return {'project': project, 'pipeline': pipeline, 'job': identifier, 'source': source,
            'name': row['name'], 'archive_size': archive['size']}


def input_job_names(member: Any) -> tuple[str, str]:
    """Exact legacy or member-scoped producer names, never a caller pattern.

    Flattened graphs need multiple freezers in one config child. Scope their
    names to the already validated member, not an arbitrary CI variable. All
    existing source, job, artifact and result checks remain mandatory.
    """
    match(member, RELEASE['TOKEN'], 'input member')
    return ('Freeze release inputs', 'Freeze release inputs ' + member)


def artifact(api, project, identifier, path, expected_sha=None):
    raw = api.get(prefix(project) + '/jobs/' + str(identifier) + '/artifacts/' + path)
    if expected_sha is not None:
        match(expected_sha, r'[0-9a-f]{64}', 'artifact digest')
        require(hashlib.sha256(raw).hexdigest() == expected_sha, 'artifact digest mismatch')
    return decode(raw)


def check_executor(row, expected, cpu):
    require(cpu in CPUS, 'unsupported executor CPU')
    architecture = CPUS[cpu]
    EXECUTOR['validate'](row, architecture,
                         (expected['executor']['source'], row['pipeline'], row['image'].split('@')[0]))
    require(row['image'] == expected['executor']['image'], 'wrong executor image')
    return architecture


def result_bytes(api, project, identifier, member, expected_sha=None):
    """Select exactly one legacy or digest-named result from a bounded job ZIP.

    Never extract paths or choose a newest result. A legacy/digest pair is
    ambiguous even when its bytes match. Other members cannot supply this one.
    """
    positive(identifier)
    match(member, RELEASE['TOKEN'], 'result member')
    raw = api.get(prefix(project) + '/jobs/' + str(identifier) + '/artifacts')
    require(len(raw) <= RELEASE['LIMIT'], 'oversized result archive')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) <= 256 and sum(e.file_size for e in entries) <= RELEASE['LIMIT'],
                    'oversized result archive inventory')
            names = [e.filename for e in entries]
            require(len(names) == len(set(names)), 'duplicate archive paths')
            matches = []
            for entry in entries:
                name = entry.filename
                require(not name.startswith('/') and '\\' not in name
                        and all(p not in ('', '.', '..') for p in name.rstrip('/').split('/')),
                        'unsafe archive path')
                mode = entry.external_attr >> 16
                require(not mode or stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
                        'nonregular archive entry')
                if name == 'release-results/' + member + '.json' or name.startswith('release-results/' + member + '.sha256-'):
                    found = re.fullmatch(r'release-results/' + re.escape(member)
                                         + r'(?:\.sha256-([0-9a-f]{64}))?\.json', name)
                    if found is None or entry.is_dir():
                        raise ValueError('malformed member result name')
                    matches.append((entry, found.group(1)))
            require(len(matches) == 1, 'missing or ambiguous member result')
            entry, named_sha = matches[0]
            require(not entry.flag_bits & 1, 'encrypted member result')
            with archive.open(entry) as stream:
                payload = stream.read(RELEASE['LIMIT'] + 1)
            require(len(payload) <= RELEASE['LIMIT'], 'oversized member result')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as error:
        raise ValueError('invalid result archive') from error
    actual_sha = hashlib.sha256(payload).hexdigest()
    require(named_sha is None or named_sha == actual_sha, 'result filename digest mismatch')
    if expected_sha is not None:
        match(expected_sha, r'[0-9a-f]{64}', 'result digest')
        require(expected_sha == actual_sha, 'result artifact digest mismatch')
    decode(payload)
    return payload


def check_result(expected, row, selector):
    indexed = RELEASE['expectations'](expected)
    fields(row, 'schema kind release expectations_digest executor_receipt output', 'member result')
    require(type(row['schema']) is int and row['schema'] == 1
            and row['kind'] == 'nest_release_member_result', 'unsupported member result')
    require(row['release'] == expected['release'] and row['expectations_digest'] == RELEASE['digest'](expected),
            'member result input binding mismatch')
    member = indexed[selector['member']]
    output = row['output']
    require(output['member'] == member and member['project'] == selector['project'], 'wrong predecessor member')
    require(output['producer'] == {'project': selector['project'], 'sha': expected['sources'][selector['project']],
                                   'pipeline': selector['pipeline'], 'job': selector['job']}, 'wrong predecessor job')
    check_executor(row['executor_receipt'], expected, member['cpu'])
    # Reuse the strict existing output schema on this exact member, without
    # claiming that unrelated outputs in the original matrix have completed.
    subset = copy.deepcopy(expected)
    subset['members'] = [member]
    for consumer in subset['consumers']:
        consumer['members'] = [member['id']] if consumer['project'] == member['project'] else []
        if consumer['project'] != member['project']:
            consumer['decision'] = 'defer'
    candidate = {'schema': 1, 'kind': 'nest_release_candidate', 'release': expected['release'],
                 'expectations_digest': RELEASE['digest'](subset), 'outputs': [output]}
    RELEASE['validate'](subset, candidate)
    return output


def compatible(target, base, source, role):
    """Existing fresh/refresh recipe semantics; metadata is not hardware proof."""
    require(target['cpu'] == source['cpu'] or
            (target['project'] == 'nest/tools/firefox' and target['mode'] == 'fresh'
             and target['cpu'] == 'zen5' and source['cpu'] == 'haswell'), 'incompatible base CPU')
    require(target['variant'] == source['variant'] or
            (target['stage'] == 'stage1' and target['mode'] == 'fresh' and source['stage'] == 'stage0'
             and source['variant'] == 'server'), 'incompatible base variant')
    stage, mode = target['stage'], target['mode']
    if stage == 'stage1':
        require(source['stage'] == ('stage0' if mode == 'fresh' else 'stage1')
                and role == base, 'wrong Stage 1 base role')
    elif stage == 'stage2':
        require(base == 'image' and source['stage'] == ('stage1' if mode == 'fresh' else 'stage2')
                and role == ('debug' if mode == 'fresh' else 'image'), 'wrong Stage 2 base role')
    elif stage == 'stage3':
        require(mode == 'fresh' and base == 'image' and source['stage'] == 'stage2'
                and role == 'image', 'wrong Stage 3 base role')
    elif stage == 'tool':
        require(target['project'] in TOOLS and base == 'image'
                and source['stage'] == ('stage1' if mode == 'fresh' else 'tool')
                and role == ('normal' if mode == 'fresh' else 'image'), 'wrong tool base role')
        require(mode != 'refresh' or target['project'] == source['project'], 'wrong refreshed tool')
    else:
        require(stage == 'stage0' and mode == 'refresh' and source['stage'] == 'stage0'
                and base == 'image' and role == 'normal', 'unsupported base edge')
    if source['stage'] == 'stage0':
        # Stage 0's server-profile pair seeds all Stage 1 variants.
        require(stage in ('stage0', 'stage1'), 'wrong Stage 0 consumer')
    if source['stage'] == 'stage2':
        require(target['platform'] == source['platform']
                and target['compatibility'] == source['compatibility'], 'incompatible platform or boot policy')


def bind(request: Any, api):
    fields(request, 'schema kind expectations executor_job producers bindings', 'binding request')
    require(type(request['schema']) is int and request['schema'] == 1
            and request['kind'] == 'nest_release_base_binding', 'unsupported binding request')
    expected = copy.deepcopy(request['expectations'])
    indexed = RELEASE['expectations'](expected)
    producers, bindings = request['producers'], request['bindings']
    require(type(producers) is dict and 0 < len(producers) <= 128, 'invalid predecessor inventory')
    require(type(bindings) is list and 0 < len(bindings) <= 2048, 'invalid base binding inventory')
    selected = {}
    touched = set()
    for edge in bindings:
        fields(edge, 'target base producer artifact', 'base binding')
        require(type(edge['target']) is str and edge['target'] in indexed
                and type(edge['producer']) is str and edge['producer'] in producers, 'unknown base binding')
        member = indexed[edge['target']]
        require(edge['base'] in member['bases'] and edge['artifact'] in ('normal', 'debug', 'image'), 'wrong base slot')
        key = (edge['target'], edge['base'])
        require(key not in touched, 'duplicate base binding')
        touched.add(key)
        selected[member['id']] = member
    require({edge['producer'] for edge in bindings} == set(producers), 'unused predecessor')
    # Each invocation freezes one architecture group. Separate invocations may
    # share source/member selection but never pretend an amd64 image is arm64.
    require(all(member['cpu'] in CPUS for member in expected['members']), 'unsupported executor CPU')
    architectures = {CPUS[member['cpu']] for member in expected['members']}
    require(len(architectures) == 1, 'mixed executor architectures')
    for member in selected.values():
        require({(member['id'], slot) for slot in member['bases']} <= touched, 'partial member base binding')
        require(next(c['decision'] for c in expected['consumers'] if c['project'] == member['project']) == 'rebuild',
                'only rebuilt descendants may be rebound')
        if member['stage'] == 'stage1':
            require(len({edge['producer'] for edge in bindings if edge['target'] == member['id']}) == 1,
                    'Stage 1 base pair has different producers')
    fields(request['executor_job'], 'pipeline job', 'executor job')
    executor_selector = request['executor_job']
    config_source = expected['sources']['nest/config']
    executor_job = job(api, 'nest/config', executor_selector['pipeline'], executor_selector['job'], expected['executor']['source'])
    architecture = next(iter(architectures))
    require(executor_job['name'] == 'Build ' + architecture, 'wrong executor job')
    executor = artifact(api, 'nest/config', executor_selector['job'], 'executor-receipts/' + architecture + '.json')
    check_executor(executor, expected, expected['members'][0]['cpu'])
    require(executor['job'] == executor_selector['job'] and executor['pipeline'] == executor_selector['pipeline'],
            'executor receipt resource mismatch')
    observations = [(executor_job, None)]
    outputs = {}
    for name, selector in producers.items():
        match(name, RELEASE['TOKEN'], 'predecessor name')
        fields(selector, 'project pipeline job member input_pipeline input_job input_sha256 result_sha256', 'predecessor')
        match(selector['member'], RELEASE['TOKEN'], 'predecessor member')
        require(selector['project'] in expected['sources'], 'missing predecessor source')
        source = expected['sources'][selector['project']]
        actual_job = job(api, selector['project'], selector['pipeline'], selector['job'], source)
        input_job = job(api, 'nest/config', selector['input_pipeline'], selector['input_job'], config_source)
        require(input_job['name'] in input_job_names(selector['member']), 'wrong predecessor input job')
        original = artifact(api, 'nest/config', selector['input_job'], 'release-inputs/expectations.json', selector['input_sha256'])
        require(original['sources'] == expected['sources'] and original['release'] == expected['release']
                and original['schema'] == expected['schema'] and original['executor'] == expected['executor'],
                'predecessor uses different release or source closure')
        row = decode(result_bytes(api, selector['project'], selector['job'], selector['member'], selector['result_sha256']))
        outputs[name] = check_result(original, row, selector)
        observations.extend(((actual_job, selector['result_sha256']), (input_job, selector['input_sha256'])))
    changes = []
    for edge in bindings:
        member = indexed[edge['target']]
        output = outputs[edge['producer']]
        compatible(member, edge['base'], output['member'], edge['artifact'])
        reference = output['artifacts'][edge['artifact']]
        changes.append({'target': member['id'], 'base': edge['base'], 'before': member['bases'][edge['base']],
                        'after': reference, 'producer': output['producer'], 'artifact': edge['artifact']})
        member['bases'][edge['base']] = reference
    RELEASE['expectations'](expected)
    # Resource status/erasure rechecked across artifact acquisition and binding.
    for observation, _ in observations:
        require(job(api, observation['project'], observation['pipeline'], observation['job'], observation['source']) == observation,
                'producer resource changed during binding')
    receipt = {'schema': 1, 'kind': 'nest_release_base_binding_result', 'release': expected['release'],
               'before_expectations_digest': RELEASE['digest'](request['expectations']),
               'expectations_digest': RELEASE['digest'](expected), 'changes': changes,
               'executor_job': executor_job,
               'predecessors': [{'job': observation, 'artifact_sha256': sha} for observation, sha in observations[1:]],
               'resource_verification': 'successful_gitlab_jobs_and_exact_artifact_bytes_only',
               'image_compatibility_verification': 'not_performed', 'promotion_authorized': False}
    return expected, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--output-dir', help='existing canonical directory for content-addressed binding package')
    args = parser.parse_args()
    try:
        expected, receipt = bind(RELEASE['load'](args.binding), GitLab())
        package = {'schema': 1, 'kind': 'nest_release_bound_inputs', 'expectations': expected, 'binding': receipt}
        expectations_path = RELEASE['retain'](args.output_dir, RELEASE['canonical'](expected)) if args.output_dir else None
        path = RELEASE['retain'](args.output_dir, RELEASE['canonical'](package)) if args.output_dir else None
        print(json.dumps({'schema': 1, 'expectations_digest': receipt['expectations_digest'],
                          'bindings': len(receipt['changes']), 'path': path, 'expectations_path': expectations_path,
                          'readback_verified': path is not None,
                          'input_publication': 'not_performed', 'promotion_authorized': False}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, StopIteration, RecursionError, subprocess.SubprocessError):
        print('Release base binding refused or failed; no accepted inputs published', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
