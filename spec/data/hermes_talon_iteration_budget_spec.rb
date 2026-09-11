require 'spec_helper'
require 'yaml'

RSpec.describe 'Talon Hermes iteration budget' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:owl_data) { YAML.safe_load_file(File.join(repo_root, 'data/host/owl.yaml'), aliases: true) }
  let(:profiles) { owl_data.fetch('nest::app::hermes::instances') }
  let(:config_manifest) { File.read(File.join(repo_root, 'manifests/app/hermes/config.pp')) }
  let(:profile_manifest) { File.read(File.join(repo_root, 'manifests/lib/hermes.pp')) }

  it 'renders a finite 180-turn limit only for Talon' do
    expect(profiles.fetch('talon').fetch('agent_max_turns')).to eq(180)
    expect(profiles.reject { |name, _profile| name == 'talon' }.values).to all(satisfy do |profile|
      !profile.key?('agent_max_turns')
    end)

    expect(config_manifest).to include("pick($config['agent_max_turns'], 90)")
    expect(config_manifest).to include('agent_max_turns            => $instance_agent_max_turns')
    expect(profile_manifest).to include("'max_turns' => $agent_max_turns")
  end
end
