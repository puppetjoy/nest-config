require 'spec_helper'
require 'yaml'

describe 'nest::app::hermes' do
  on_supported_os.each do |os, facts|
    next unless os.match?(%r{^gentoo-})

    context 'with production and development GitLab MR note pollers enabled' do
      let(:facts) do
        facts.merge(systemd_version: '255')
      end

      let(:pre_condition) do
        <<~PUPPET
          class python (
            Boolean $manage_python_package = true,
            Boolean $manage_pip_package    = true,
            Boolean $manage_venv_package   = true,
          ) {}

          define python::pyvenv (
            $ensure      = present,
            $version     = 'system',
            $python_path = '/usr/bin/python3',
            $owner       = 'root',
            $group       = 'root',
          ) {
            exec { "python_virtualenv_${title}":
              command => '/bin/true',
              creates => "${title}/bin/activate",
            }
          }

          define python::pip (
            $ensure      = present,
            $pkgname     = $title,
            $extras      = [],
            $virtualenv  = undef,
            $environment = [],
          ) {}

          class { 'nest':
            kernel_tag      => 'stable/v6.18.21',
            nestfs_hostname => 'nestfs.example.com',
            openvpn_servers => [],
            classes         => [],
          }
        PUPPET
      end

      let(:params) do
        {
          gitlab_mr_note_poller_enabled: true,
          gitlab_mr_note_dev_enabled: true,
          instances: {
            'talon' => {
              'soul_content' => 'test soul',
              'gitlab_enabled' => true,
              'gitlab_token' => 'fixture-token',
              'dashboard_enabled' => true,
            },
          },
        }
      end

      let(:production_service_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes.service' }
      let(:development_service_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes-dev.service' }
      let(:production_timer_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes.timer' }
      let(:development_timer_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes-dev.timer' }

      it { is_expected.to compile }
      it { is_expected.to contain_python__pyvenv('/opt/hermes-agent/venv').with_python_path('/usr/bin/python3.13').that_requires('Package[dev-lang/python:3.13]') }
      it 'checks a new virtualenv through an existing shell before its interpreter exists' do
        guard = catalogue.resource('Exec', 'python_virtualenv_/opt/hermes-agent/venv')[:unless]

        expect(guard).to eq("/bin/sh -c \"test -x /opt/hermes-agent/venv/bin/python && /opt/hermes-agent/venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 13)'\"")
      end
      it { is_expected.to contain_exec('build_hermes_tui').that_requires('Exec[install_hermes_npm]') }
      it 'refreshes gateways for real runtime and glab changes, not UI build receipts' do
        subscriptions = catalogue.resource('Exec', 'restart_hermes_gateway_talon')[:subscribe].map(&:to_s)

        expect(subscriptions).to include('Exec[install_hermes_agent]', 'Exec[install_hermes_agent_request_broker]', 'Exec[configure_hermes_glab_talon]')
        expect(subscriptions).not_to include('Exec[build_hermes_tui]', 'Exec[build_hermes_dashboard_web]')
        expect(catalogue.resource('Exec', 'restart_hermes_gateway_talon')[:refreshonly]).to be true
        expect(catalogue.resource('File', '/home/joy/.hermes/profiles/talon/glab/config.yml')[:replace]).to be false
      end
      it { is_expected.to contain_file(production_timer_path).with_ensure('file') }
      it { is_expected.to contain_file(development_timer_path).with_ensure('file') }
      it { is_expected.to contain_systemd__user_service('hermes-agent-request-gitlab-mr-notes').with_unit('hermes-agent-request-gitlab-mr-notes.timer') }
      it { is_expected.to contain_systemd__user_service('hermes-agent-request-gitlab-mr-notes-dev').with_unit('hermes-agent-request-gitlab-mr-notes-dev.timer') }

      it 'isolates the production poller board and GitLab host' do
        content = catalogue.resource('File', production_service_path)[:content]

        expect(content).to include('Environment=AGENT_REQUEST_KANBAN_BOARD=agent-requests')
        expect(content).to include('Environment=GITLAB_URL=https://gitlab.joyfullee.me')
        expect(content).to include('--board agent-requests --gitlab-url https://gitlab.joyfullee.me')
        expect(content).not_to include('agent-requests-dev')
        expect(content).not_to include('gitlab-test.eyrie')
      end

      it 'isolates the development poller board and GitLab host' do
        content = catalogue.resource('File', development_service_path)[:content]

        expect(content).to include('Environment=AGENT_REQUEST_KANBAN_BOARD=agent-requests-dev')
        expect(content).to include('Environment=GITLAB_URL=https://gitlab-test.eyrie')
        expect(content).to include('--board agent-requests-dev --gitlab-url https://gitlab-test.eyrie')
        expect(content).not_to match(%r{AGENT_REQUEST_KANBAN_BOARD=agent-requests(?:\s|$)})
        expect(content).not_to include('gitlab.joyfullee.me')
      end

      context 'with the coordinated PM cutover explicitly activated' do
        let(:params) do
          super().merge(pm_enabled: true, git_commit: 'a' * 40, broker_git_ref: 'b' * 40)
        end

        it { is_expected.to compile.with_all_deps }
        it { is_expected.not_to contain_python__pyvenv('/opt/hermes-agent/venv') }
        it { is_expected.not_to contain_python__pip('hermes-agent-honcho-deps') }
        it { is_expected.to contain_class('nest::app::hermes::extracted_plugins') }
        it { is_expected.to contain_exec('install_hermes_agent').that_requires('Class[nest::app::hermes::extracted_plugins]') }

        it 'uses PM launch selection for gateway and profile commands' do
          wrapper = catalogue.resource('File', '/usr/local/bin/talon')[:content]
          service = catalogue.resource('Systemd::Manage_unit', 'hermes-gateway@.service')[:service_entry]

          expect(wrapper).to include('/opt/hermes-agent/bin/hermes-python')
          expect(wrapper).not_to include('/venv/bin/hermes')
          expect(service['ExecStart']).to include('/opt/hermes-agent/bin/hermes-python -m hermes_cli.main')
        end

        it 'retains external plugin dependencies and migrates the selected browser toolset' do
          config = YAML.safe_load(catalogue.resource('File', '/home/joy/.hermes/profiles/talon/managed-config.yaml')[:content])

          expect(config.fetch('plugins').fetch('enabled')).to include('camofox', 'nest-agent-request-broker')
          expect(config.fetch('platform_toolsets').fetch('telegram')).to include('browser', 'camofox')
        end

        context 'with normal rolling core and broker refs' do
          let(:params) { super().merge(git_commit: :undef, git_ref: 'nest', broker_git_ref: 'main') }

          it { is_expected.to compile.with_all_deps }
          it { is_expected.not_to contain_exec('verify_hermes_source_ref_pin') }
          it { is_expected.to contain_exec('install_hermes_agent').that_requires('Exec[verify_hermes_pm_checkpoint]') }
          it { is_expected.to contain_file('/opt/hermes-agent/bin/hermes-python').that_requires('Exec[install_hermes_agent]') }
        end
      end
    end
  end
end
