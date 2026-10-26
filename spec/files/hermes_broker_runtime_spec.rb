require 'spec_helper'
require 'yaml'

describe 'Hermes broker runtime deployment boundary' do
  let(:root) { File.expand_path('../..', __dir__) }
  let(:owl) { YAML.safe_load_file(File.join(root, 'data/host/owl.yaml'), aliases: true) }
  let(:install) { File.read(File.join(root, 'manifests/app/hermes/install.pp')) }
  let(:service) { File.read(File.join(root, 'manifests/app/hermes/service.pp')) }
  let(:tag) { "tag         => 'hermes_agent_request_broker_runtime'" }

  it 'pins the merged broker independently of the Hermes core' do
    expect(owl.fetch('nest::app::hermes::broker_git_ref')).to eq('c44e20daa6fe9261701ac0cf45ed9fcd2b141c0f')
    expect(owl.fetch('nest::app::hermes::git_ref')).to eq('nest')
    expect(owl.fetch('nest::app::hermes::git_commit')).to match(%r{\A[0-9a-f]{40}\z})
  end

  it 'gives the watchdog the managed poller environment and configured GitLab host' do
    unit = service.split('file { "${systemd_user_dir}/hermes-agent-request-moving-tickets.service":', 2).last.split('| UNIT', 2).first
    expect(unit).to include('EnvironmentFile=-${hermes_home_dir}/profiles/${gitlab_mr_note_poller_profile}/systemd.env')
    expect(unit).to include('Environment=GITLAB_URL=${nest::app::hermes::gitlab_url}')
    expect(unit).to include("tag     => 'hermes_agent_request_watchdog_runtime'")
    expect(unit).to include('Environment=AGENT_REQUEST_KANBAN_BOARD=${nest::app::hermes::agent_request_kanban_board}')
  end

  it 'restricts the runtime tag to the broker checkout and install' do
    tagged = install.scan(%r{(?:vcsrepo|exec|file) \{ ([^\n]+):\n(.*?)^  \}}m).select { |_title, body| body.include?('hermes_agent_request_broker_runtime') }
    expect(tagged.map(&:first)).to contain_exactly('$broker_source_dir', "'install_hermes_agent_request_broker'")
    expect(tagged.last.last).to include(tag)
    expect(tagged.first.last).to include('revision => $broker_git_ref')
    expect(tagged.last.last).to include('Vcsrepo[$broker_source_dir]')
  end
end
