require 'spec_helper'
require 'yaml'
require 'open3'
require 'json'

describe 'Hermes broker runtime deployment boundary' do
  let(:root) { File.expand_path('../..', __dir__) }
  let(:owl) { YAML.safe_load_file(File.join(root, 'data/host/owl.yaml'), aliases: true) }
  let(:install) { File.read(File.join(root, 'manifests/app/hermes/install.pp')) }
  let(:service) { File.read(File.join(root, 'manifests/app/hermes/service.pp')) }
  let(:tag) { "tag         => 'hermes_agent_request_broker_runtime'" }

  it 'keeps PM core rolling and broker releases independently pinned' do
    expect(owl.fetch('nest::app::hermes::pm_enabled')).to be(true)
    expect(owl.fetch('nest::app::hermes::broker_git_ref')).to match(%r{\A[0-9a-f]{40}\z})
    # The default remains rolling; the coordinated release host is source-pinned.
    expect(File.read(File.join(root, 'manifests/app/hermes.pp'))).to match(%r{\$git_ref\s*=\s*'main'})
    expect(owl.fetch('nest::app::hermes::git_ref')).to eq('nest')
    expect(owl.fetch('nest::app::hermes::git_commit')).to eq('be49faf1424d2d5ee279e86666d1ecf716f148cf')
  end

  it 'removes the applying lifecycle reconciler while retaining GitLab note ingress' do
    expect(service).not_to include('agent-request-reconcile-moving-tickets', 'hermes-agent-request-moving-tickets')
    expect(service).to include('hermes-agent-request-gitlab-mr-notes.timer')
    expect(service).to include('agent_request_broker.gitlab_mr_note_poller')
    expect(File.read(File.join(root, 'manifests/app/hermes.pp'))).not_to include('moving_ticket_enabled', 'moving_ticket_interval')
  end

  it 'executes the rendered broker entrypoint to register native observers and commands' do
    entrypoint = install.match(%r{file \{ "\$\{broker_source_dir\}/__init__\.py":\n.*?content => (".*?"),}m)[1]
    rendered = JSON.parse(entrypoint)
    harness = <<~PYTHON
      import sys, types
      calls = []
      backend = types.ModuleType('agent_request_broker.kanban_backend')
      backend.on_kanban_task_blocked = lambda *a, **k: None
      terminal = types.ModuleType('agent_request_broker.native_terminal_notification')
      terminal.on_completed = lambda *a, **k: None
      junior = types.ModuleType('agent_request_broker.junior_owner_command')
      junior.authorize_command = lambda *a, **k: None
      defect = types.ModuleType('agent_request_broker.owner_defect_command')
      defect.request_command = lambda *a, **k: None
      package = types.ModuleType('agent_request_broker')
      package.__path__ = []
      sys.modules[package.__name__] = package
      writer = types.ModuleType('agent_request_broker.blocked_writer_plugin')
      # This unit models the delegated broker API, not its implementation.
      def register_writer(context):
          context.register_command('independent-defect', defect.request_command)
          context.register_command('junior-authorize', junior.authorize_command)
          context.register_hook('kanban_task_blocked', backend.on_kanban_task_blocked)
          context.register_hook('kanban_task_completed', terminal.on_completed)
      writer.register = register_writer
      for module in (backend, terminal, junior, defect, writer): sys.modules[module.__name__] = module
      class Context:
          def register_hook(self, name, callback): calls.append(('hook', name, callback))
          def register_command(self, name, callback, **kwargs): calls.append(('command', name, callback))
      namespace = {}
      exec(ENTRYPOINT, namespace)
      namespace['register'](Context())
      assert {(kind, name) for kind, name, _ in calls} == {
          ('hook', 'kanban_task_blocked'), ('hook', 'kanban_task_completed'),
          ('command', 'independent-defect'), ('command', 'junior-authorize')}
      assert next(callback for kind, name, callback in calls if (kind, name) == ('hook', 'kanban_task_blocked')) is backend.on_kanban_task_blocked
      assert next(callback for kind, name, callback in calls if (kind, name) == ('hook', 'kanban_task_completed')) is terminal.on_completed
    PYTHON
    script = harness.sub('ENTRYPOINT', rendered.dump)
    stdout, stderr, status = Open3.capture3('python3', '-c', script)
    expect(status).to be_success, "rendered entrypoint failed: #{stdout}#{stderr}"
  end

  it 'uses a minimal replacement broker package contract without retired lifecycle APIs' do
    expect(install).not_to include('trusted_accept_review', 'resume_blocked_task_from_reply', '_reply_prompt_stale_reason')
    expect(install).to include('import agent_request_broker.kanban_backend')
    expect(install).to include('rev-parse HEAD)')
    expect(install).to include('cat ${broker_git_revision_file}')
    broker_revision_guard = install.lines.find { |line| line.include?('unless') && line.include?('${broker_git_revision_file}') }
    expect(broker_revision_guard).to match(%r{test .*rev-parse HEAD.* = .*cat.*broker_git_revision_file})
  end

  it 'restricts the runtime tag to the broker checkout and install' do
    tagged = install.scan(%r{(?:vcsrepo|exec|file) \{ ([^\n]+):\n(.*?)^  \}}m).select { |_title, body| body.include?('hermes_agent_request_broker_runtime') }
    expect(tagged.map(&:first)).to contain_exactly('$broker_source_dir', "'install_hermes_agent_request_broker'")
    expect(tagged.last.last).to include(tag)
    expect(tagged.first.last).to include('revision => $broker_git_ref')
    expect(tagged.last.last).to include('Vcsrepo[$broker_source_dir]')
  end
end
