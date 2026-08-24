require 'spec_helper'
require 'yaml'

RSpec.describe 'Star Hermes approval policy' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:owl_data) { YAML.safe_load_file(File.join(repo_root, 'data/host/owl.yaml'), aliases: true) }
  let(:star) { owl_data.fetch('nest::app::hermes::instances').fetch('star') }

  it 'keeps manual approval mode while allowing the Python forms Star uses' do
    expect(star.fetch('approval_mode', 'manual')).to eq('manual')
    expect(star.fetch('command_allowlist')).to eq(
      [
        'execute_code',
        'python *',
        'python3 *',
        '/opt/hermes-agent/venv/bin/python *',
        'HERMES_HOME=* /opt/hermes-agent/venv/bin/python *',
        'uv run python *',
        'uv run --with * python *',
      ],
    )
  end

  it 'does not allowlist compound shell syntax or non-Python commands' do
    allowlist = star.fetch('command_allowlist')

    expect(allowlist.grep(%r{\n|&&|\|\||[;&|<>`]|\$\(})).to be_empty
    expect(allowlist).not_to include('*', 'sh *', 'bash *', 'sudo *')
  end
end
