require 'open3'
require 'spec_helper'
require 'yaml'

RSpec.describe 'Pattern Kit Eyrie deployment assets' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:app_path) { File.join(repo_root, 'data/kubernetes/app/patternkit.yaml') }
  let(:app) { YAML.safe_load_file(app_path, aliases: true) }
  let(:resources) { app.fetch('resources') }

  it 'keeps Studio and the workbench on explicit, isolated state boundaries' do
    studio = resources.fetch('studio').dig('spec', 'template', 'spec')
    workbench = resources.fetch('workbench').dig('spec', 'template', 'spec')

    expect(studio.fetch('volumes').map { |volume| volume.fetch('name') }).to include('patternkit-source', 'atelier-source', 'sessions')
    expect(workbench.fetch('volumes').map { |volume| volume.fetch('name') }).to include('profile')
    expect(workbench.to_s).not_to include('firefox-profile', 'browser.eyrie', 'transient-target')
    expect(resources.fetch('workbench-profile').dig('metadata', 'labels', 'joyfullee.me/isolation-boundary')).to eq('dedicated-profile')
  end

  it 'pins accepted source and browser-image revisions and enforces GitLab OAuth' do
    expect(app.fetch('patternkit_revision')).to match(%r{\A[0-9a-f]{40}\z})
    expect(app.fetch('atelier_revision')).to match(%r{\A[0-9a-f]{40}\z})
    expect(app.fetch('runtime_image')).to match(%r{@sha256:[0-9a-f]{64}\z})
    expect(app.fetch('firefox_image')).to match(%r{@sha256:[0-9a-f]{64}\z})
    expect(app.fetch('oauth_client_id')).to match(%r{\A[0-9a-f]{64}\z})

    [resources.fetch('studio'), resources.fetch('workbench')].each do |deployment|
      expect(deployment.dig('spec', 'template', 'spec', 'automountServiceAccountToken')).to be(false)
      containers = deployment.dig('spec', 'template', 'spec', 'containers')
      expect(containers.map { |container| container.fetch('name') }).to include('oauth-proxy')
    end
  end

  it 'keeps exact-tab identity fail closed across tab and browser changes' do
    bridge = File.read(File.join(repo_root, 'files/app/patternkit/workbench_bridge.py'))

    expect(bridge).to include('browser_start_identity')
    expect(bridge).to include('getactivewindow')
    expect(bridge).to include('len(matches) != 1')
    expect(bridge).to include('active_url.hostname != "127.0.0.1"')
    expect(bridge).to include('"target_id": active_context["id"]')
    expect(bridge).to include('"selected_context": state.get("target_id")')
    expect(bridge).to include('len(active_bindings) == 1')
    expect(bridge).to include('and state.get("target_id")')
    expect(bridge).to include('secrets.compare_digest')
    expect(bridge).to include('explicit-share-required')
    expect(bridge).not_to include('last_nonblank')
    expect(bridge).not_to include('windowactivate')
  end

  it 'routes the Star session bridge through the exact isolated service boundary' do
    studio = resources.fetch('studio').dig('spec', 'template', 'spec', 'containers')
    studio_proxy = studio.find { |container| container.fetch('name') == 'oauth-proxy' }
    workbench = resources.fetch('workbench').dig('spec', 'template', 'spec', 'containers')
    firefox = workbench.find { |container| container.fetch('name') == 'firefox' }
    studio_environment = studio_proxy.fetch('env').to_h { |item| [item.fetch('name'), item] }
    firefox_environment = firefox.fetch('env').to_h { |item| [item.fetch('name'), item] }

    expect(studio_environment.fetch('OAUTH_PROXY_BRIDGE_TOKEN').dig('valueFrom', 'secretKeyRef', 'name')).to eq('%{nest::kubernetes::service}-smoke')
    expect(studio_environment.fetch('OAUTH_PROXY_BRIDGE_TOKEN').dig('valueFrom', 'secretKeyRef', 'key')).to eq('studio-bridge-token')
    expect(firefox_environment.fetch('PATTERNKIT_STUDIO_PROXY').fetch('value')).to eq('http://%{nest::kubernetes::service}-workbench-egress:3128')
    expect(firefox_environment.fetch('PATTERNKIT_BRIDGE_TOKEN').dig('valueFrom', 'secretKeyRef', 'key')).to eq('token')
    expect(firefox_environment.fetch('PATTERNKIT_AGENT_TOKEN').dig('valueFrom', 'secretKeyRef', 'key')).to eq('agent-token')
    expect(firefox_environment.fetch('PATTERNKIT_STUDIO_BRIDGE_TOKEN').dig('valueFrom', 'secretKeyRef', 'key')).to eq('studio-bridge-token')
    expect(firefox.fetch('command').last).to include('unset PATTERNKIT_BRIDGE_TOKEN PATTERNKIT_AGENT_TOKEN PATTERNKIT_STUDIO_BRIDGE_TOKEN')
    expect(firefox.fetch('command').last.index('unset PATTERNKIT_BRIDGE_TOKEN')).to be < firefox.fetch('command').last.index('exec /usr/local/bin/nest-firefox-browser')
    expect(resources.fetch('workbench-egress-isolation').to_s).to include('workbench-egress', '3128')
  end

  it 'binds OAuth state to the browser and tunnels WebSockets bidirectionally' do
    proxy = File.read(File.join(repo_root, 'files/app/patternkit/oauth_proxy.py'))

    expect(proxy).to include('STATE_COOKIE_NAME')
    expect(proxy).to include('secrets.compare_digest(cookie_state, state)')
    expect(proxy).to include('cookies=(cookie, clear_state)')
    expect(proxy).to include('self.headers.get("Transfer-Encoding")')
    expect(proxy).to include('upstream_cookie = _upstream_cookie(value)')
    expect(proxy).to include('select.select(sockets, [], [])')
    expect(proxy).to include('destination = upstream if source is self.connection else self.connection')
  end

  it 'uses loopback exec probes and a dedicated hostname-aware workbench egress boundary' do
    studio = resources.fetch('studio').dig('spec', 'template', 'spec')
    studio_container = studio.fetch('containers').find { |container| container.fetch('name') == 'studio' }
    isolation = resources.fetch('workbench-egress-isolation').fetch('spec')
    ingress = resources.fetch('workbench-ingress-isolation').fetch('spec')
    proxy = resources.fetch('workbench-egress').dig('spec', 'template', 'spec')

    expect(studio_container.dig('readinessProbe', 'exec', 'command').join(' ')).to include('127.0.0.1:8765/api/health')
    expect(isolation.fetch('podSelector').fetch('matchLabels').fetch('app')).to include('workbench')
    expect(isolation.to_s).to include('workbench-egress', '3128')
    expect(isolation.to_s).not_to include('0.0.0.0/0', '::/0')
    expect(ingress.to_s).to include('4180', '8766')
    expect(ingress.to_s).not_to include('6901')
    expect(proxy.fetch('automountServiceAccountToken')).to be(false)
    expect(resources.fetch('workbench-browser-policy').to_s).to include('workbench-egress', 'UseHTTPProxyForAllProtocols')
  end

  it 'proves owl placement and private workbench identity in synthetic smoke checks' do
    smoke = resources.fetch('smoke-test').dig('spec', 'jobTemplate', 'spec', 'template', 'spec', 'containers').first
    environment = smoke.fetch('env').to_h { |item| [item.fetch('name'), item['value']] }
    script = File.read(File.join(repo_root, 'files/app/patternkit/smoke_test.py'))

    expect(environment.fetch('PATTERNKIT_WORKBENCH_BRIDGE_URL')).to include('%{nest::kubernetes::service}-workbench:8766')
    expect(script).to include('binding.get("isolated_browser_verified")')
    expect(script).to include('X-PatternKit-Bridge-Token')
    expect(script).to include('workbench_bridge_unauth_status')
    expect(script).to include('/synthetic-contract')
    expect(script).to include('verify_hot_reload')
    expect(script).to include('/api/session?name=deployment-smoke')
    expect(script).to include('PATTERNKIT_EXPECTED_SESSION_CREATED_AT')
    expect(resources.fetch('smoke-test').to_s).to include('PATTERNKIT_HOT_RELOAD_PATH', 'kubectl patch deployment')
    expect(resources.fetch('smoke-role').dig('rules', 0, 'resourceNames')).to eq(['%{nest::kubernetes::service}'])
    expect(resources.fetch('smoke-role').to_s).not_to include('pods/log', 'delete')
  end

  it 'checks OAuth redirects with the lowercase headers emitted by Envoy' do
    script = File.read(File.join(repo_root, 'files/app/patternkit/smoke_test.py'))

    expect(script).to include('headers.get("location", "")')
  end

  it 'ships Python assets that compile in CI' do
    scripts = ['oauth_proxy.py', 'egress_proxy.py', 'workbench_bridge.py', 'smoke_test.py'].map do |name|
      File.join(repo_root, 'files/app/patternkit', name)
    end
    scripts << File.join(repo_root, 'files/app/hermes/patternkit_session_broker.py')
    compile = 'import pathlib, sys; [compile(pathlib.Path(path).read_bytes(), path, "exec") for path in sys.argv[1:]]'
    _stdout, stderr, status = Open3.capture3('python3', '-c', compile, *scripts)

    expect(status).to be_success, stderr
  end

  it 'rejects stale, duplicate, and inexact workbench bindings' do
    test_path = File.join(repo_root, 'spec/files/patternkit_workbench_bridge_test.py')
    _stdout, stderr, status = Open3.capture3('python3', test_path)

    expect(status).to be_success, stderr
  end

  it 'keeps upstream application cookies without leaking proxy credentials' do
    test_path = File.join(repo_root, 'spec/files/patternkit_oauth_proxy_test.py')
    _stdout, stderr, status = Open3.capture3('python3', test_path)

    expect(status).to be_success, stderr
  end

  it 'keeps workbench browser egress on the exact destination allowlist' do
    test_path = File.join(repo_root, 'spec/files/patternkit_egress_proxy_test.py')
    _stdout, stderr, status = Open3.capture3('python3', test_path)

    expect(status).to be_success, stderr
  end
end
