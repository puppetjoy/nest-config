require 'spec_helper'
require 'yaml'

RSpec.describe 'Hermes main model assignments' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:owl_data) { YAML.safe_load_file(File.join(repo_root, 'data/host/owl.yaml'), aliases: true) }
  let(:instances) { owl_data.fetch('nest::app::hermes::instances') }

  it 'assigns the requested GPT-6 main models' do
    expect(instances.fetch('talon')).to include(
      'model_provider' => 'openai-codex',
      'model_name' => 'gpt-6-sol',
    )
    expect(instances.fetch('star')).to include(
      'model_provider' => 'openai-codex',
      'model_name' => 'gpt-6-astra',
    )
    expect(instances.fetch('quill')).to include(
      'model_provider' => 'copilot',
      'model_name' => 'gpt-6-luna',
    )
  end

  it 'leaves Beryl and all auxiliary and delegation routes unchanged' do
    expect(instances.fetch('beryl')).to include(
      'model_provider' => 'custom:llama-qwen',
      'model_name' => 'qwen-3.6',
    )
    expect(instances.fetch('star')).not_to have_key('auxiliary_provider')
    expect(instances.fetch('star')).not_to have_key('delegation_provider')
    expect(instances.fetch('quill')).to include(
      'auxiliary_provider' => 'copilot',
      'auxiliary_compress_model' => 'gpt-5.6-terra',
      'auxiliary_extract_model' => 'gpt-5.6-terra',
      'auxiliary_title_model' => 'gpt-5.6-luna',
      'delegation_provider' => 'copilot',
      'delegation_model' => 'gpt-5.6-terra',
    )
  end
end
