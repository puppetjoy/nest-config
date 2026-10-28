"""Exercise PM-owned dependency selection through Nest's real Python-shaped launcher."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
INSTALL = Path(os.environ['NEST_PM_INSTALL']).resolve()
HELPER = ROOT / 'files/app/hermes/hermes-pm.py'


def invoke(*arguments, home):
    # Named profiles share this installation's dependency root, exactly like
    # managed ~/.hermes/profiles/<name>; unrelated data roots own their own PM state.
    profile_home = INSTALL / 'profiles' / home.name
    profile_home.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, HOME=str(home), HERMES_HOME=str(profile_home),
                       VIRTUAL_ENV='/nonexistent/legacy-venv', PYTHONPATH='/nonexistent/hostile')
    result = subprocess.run([sys.executable, '-I', str(HELPER), 'python', str(INSTALL), *arguments],
                            env=environment, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_launch_activates_union_without_inheriting_old_venv(tmp_path):
    result = json.loads(invoke('-c',
        'import sys,os,json,importlib.metadata as m; import honcho, fastapi, uvicorn, ptyprocess, googleapiclient, '
        'agent_request_broker.kanban_backend; from hermes_constants import get_hermes_home; '
        'print(json.dumps({"version":list(sys.version_info[:2]),"broker":m.version("hermes-agent-request-broker"),'
        '"honcho":m.version("honcho-ai"),"home":str(get_hermes_home()),'
        '"venv":os.environ.get("VIRTUAL_ENV"),"path":sys.path}))', home=tmp_path))
    assert result['version'] == [3, 14]
    assert result['broker'] == '0.1.0'
    assert result['honcho']
    assert result['home'] == str(INSTALL / 'profiles' / tmp_path.name)
    assert result['venv'] is None
    assert '/nonexistent/hostile' not in result['path']


def test_module_and_script_launch_contracts(tmp_path):
    assert 'usage:' in invoke('-m', 'json.tool', '--help', home=tmp_path)
    script = tmp_path / 'probe.py'
    script.write_text('import sys, json; print(json.dumps(sys.argv))')
    assert json.loads(invoke(str(script), 'hello world', home=tmp_path)) == [str(script), 'hello world']


def test_staged_patch_outputs_are_present_and_hash_bound():
    import hashlib
    stage = Path(os.environ['NEST_PLUGIN_STAGE'])
    sources = json.loads((stage / 'sources.json').read_text())
    assert 'evaluation.py' in sources['honcho']['files']
    assert 'identity_audit.py' in sources['honcho']['files']
    assert 'tests/test_nest_viewport.py' in sources['camofox']['files']
    for name, row in sources.items():
        for file, digest in row['files'].items():
            assert hashlib.sha256((stage / name / file).read_bytes()).hexdigest() == digest
