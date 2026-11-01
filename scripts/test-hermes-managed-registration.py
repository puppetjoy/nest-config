"""Exercise real managed plugin discovery, schema selection and read-only dispatch.

Run only against the disposable managed install, with the empty profile and board
roots passed here. No worker, consent, external transport or lifecycle is faked.
"""
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys

root, install, home, shared = [Path(x).resolve() for x in sys.argv[1:5]]
assert install.is_relative_to(root) and home.is_relative_to(root) and shared.is_relative_to(root)
assert sys.prefix != sys.base_prefix
from hermes_constants import get_hermes_home
assert get_hermes_home().resolve() == home
assert Path(os.environ['HERMES_KANBAN_HOME']).resolve() == shared
link = install / 'src/tools/agent_request_tool.py'
assert link.is_symlink()
assert link.resolve() == install / 'agent-request-broker/src/tools/agent_request_tool.py'
assert (install / 'agent-request-broker/__init__.py').read_text() == 'from agent_request_broker.blocked_writer_plugin import register\n'

from hermes_cli.plugins import get_plugin_manager
manager = get_plugin_manager()
assert manager.home_path.resolve() == home
manager.discover_and_load()
plugins = manager.list_plugins()
actual = [p for p in plugins if p['name'] == 'agent-request-blocked-writer']
assert len(actual) == 1 and actual[0]['enabled'] and not actual[0]['error'], actual
from agent_request_broker.blocked_writer_plugin import register
from agent_request_broker.kanban_backend import on_kanban_task_blocked
from agent_request_broker.native_terminal_notification import on_completed
assert on_kanban_task_blocked in manager._hooks.get('kanban_task_blocked', [])
assert on_completed in manager._hooks.get('kanban_task_completed', [])
assert {'independent-defect', 'junior-authorize'} <= set(manager._plugin_commands)

import tools.agent_request_tool as public_tool
from tools.registry import registry
from model_tools import get_tool_definitions, handle_function_call
import jsonschema
names = set(registry.get_tool_names_for_toolset('agent_requests'))
assert 'agent_request_status' in names
entry = registry.get_entry('agent_request_status')
assert entry.handler is public_tool.agent_request_status_tool
schema = registry.get_schema('agent_request_status')
args = {'board': 'agent-requests-pm-probe', 'limit': 1}
jsonschema.Draft7Validator.check_schema(schema['parameters'])
jsonschema.validate(args, schema['parameters'])
defs = get_tool_definitions(enabled_toolsets=['agent_requests'], quiet_mode=True,
                            skip_tool_search_assembly=True)
exposed = {d['function']['name'] for d in defs}
assert 'agent_request_status' in exposed

from agent_request_broker import kanban_backend as backend
with backend.scoped_board(args['board']):
    conn = backend.connect()
    try:
        db = Path(conn.execute('PRAGMA database_list').fetchone()[2]).resolve()
        assert db.is_relative_to(shared), db
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
        before = list(conn.iterdump())
    finally:
        conn.close()
    result = handle_function_call('agent_request_status', args,
                                 enabled_tools=sorted(exposed),
                                 enabled_toolsets=['agent_requests'])
    if isinstance(result, str):
        result = json.loads(result)
    assert isinstance(result, dict) and result.get('requests') == [], result
    assert result.get('has_more') is False, result
    conn = backend.connect_status()
    try:
        after = list(conn.iterdump())
    finally:
        conn.close()
    assert before == after, 'Read-only public dispatch changed the board'

modules = [public_tool, sys.modules['agent_request_broker.kanban_backend'],
           sys.modules['hermes_cli.plugins'], sys.modules['tools.registry']]
origins = {m.__name__: {'path': m.__file__,
                       'sha256': hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}
           for m in modules}
assert all(Path(m.__file__).resolve().is_relative_to(install) for m in modules)
print(json.dumps({'managed_venv': True, 'python': sys.version, 'prefix': sys.prefix,
                  'home': str(home), 'database': str(db), 'plugin': actual[0],
                  'hooks': {'kanban_task_blocked': on_kanban_task_blocked.__module__,
                            'kanban_task_completed': on_completed.__module__},
                  'commands': sorted(manager._plugin_commands),
                  'registered_agent_request_tools': sorted(names),
                  'exposed_agent_request_tools': sorted(exposed & names),
                  'public_status_handler': entry.handler.__module__ + '.' + entry.handler.__name__,
                  'schema_validated': True, 'public_dispatch_result': result,
                  'read_only_database_equal': before == after, 'module_origins': origins}, indent=2))
