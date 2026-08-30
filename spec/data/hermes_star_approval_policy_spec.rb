require 'spec_helper'
require 'yaml'

RSpec.describe 'Star Hermes approval policy' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:owl_data) { YAML.safe_load_file(File.join(repo_root, 'data/host/owl.yaml'), aliases: true) }
  let(:star) { owl_data.fetch('nest::app::hermes::instances').fetch('star') }

  it 'gates only sudo through the managed Star command policy plugin' do
    expect(star.fetch('approval_mode')).to eq('off')
    expect(star).not_to have_key('command_allowlist')
    expect(star.fetch('enabled_plugins')).to include('star-command-policy')
  end
end
