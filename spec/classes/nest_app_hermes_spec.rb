require 'spec_helper'

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
          ) {}

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
        }
      end

      let(:production_service_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes.service' }
      let(:development_service_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes-dev.service' }
      let(:production_timer_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes.timer' }
      let(:development_timer_path) { '/home/joy/.config/systemd/user/hermes-agent-request-gitlab-mr-notes-dev.timer' }

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
    end
  end
end
