require 'spec_helper'
require 'yaml'

RSpec.describe 'Vesture secret contract' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:service_class) { File.read(File.join(repo_root, 'manifests/service/vesture.pp')) }
  let(:app_config) do
    YAML.safe_load_file(File.join(repo_root, 'data/kubernetes/app/vesture.yaml'), aliases: true)
  end
  let(:service_data) { YAML.safe_load_file(File.join(repo_root, 'data/kubernetes/service/vesture.yaml')) }
  let(:secret_data) { app_config.dig('resources', 'secrets', 'stringData') }
  let(:deployment_env_entries) do
    app_config.dig('resources', 'deployment', 'spec', 'template', 'spec', 'containers')
              .find { |container| container['name'] == 'vesture' }
              .fetch('env')
  end
  let(:deployment_env) do
    deployment_env_entries.to_h { |entry| [entry.fetch('name'), entry] }
  end

  it 'uses each deployment environment variable name exactly once' do
    names = deployment_env_entries.map { |entry| entry.fetch('name') }

    expect(names).to eq(names.uniq)
  end

  it 'does not provision or inject a browser UI password' do
    expect(service_class).not_to include('ui_password')
    expect(secret_data.keys).not_to include('VESTURE_UI_PASSWORD_SHA256')
    expect(deployment_env.keys).not_to include('VESTURE_UI_PASSWORD_SHA256')
    expect(service_data.keys).not_to include('nest::service::vesture::ui_password_sha256')
  end

  it 'preserves the session, destructive-confirmation, and scoped API secrets' do
    expect(service_class).to include('String $secret_key', 'String $star_tokens')
    expect(secret_data).to eq(
      'VESTURE_SECRET_KEY' => '%{nest::service::vesture::secret_key}',
      'VESTURE_STAR_TOKENS' => '%{nest::service::vesture::star_tokens}',
    )
    expect(deployment_env.fetch('VESTURE_SECRET_KEY')).to eq(
      'name' => 'VESTURE_SECRET_KEY',
      'valueFrom' => {
        'secretKeyRef' => {
          'name' => '%{nest::kubernetes::service}-secrets',
          'key' => 'VESTURE_SECRET_KEY',
        },
      },
    )
    expect(deployment_env.fetch('VESTURE_STAR_TOKENS')).to eq(
      'name' => 'VESTURE_STAR_TOKENS',
      'valueFrom' => {
        'secretKeyRef' => {
          'name' => '%{nest::kubernetes::service}-secrets',
          'key' => 'VESTURE_STAR_TOKENS',
        },
      },
    )
    expect(service_data.keys).to contain_exactly(
      'nest::service::vesture::secret_key',
      'nest::service::vesture::star_tokens',
    )
  end

  it 'sets the exact public origin used for same-origin mutation checks' do
    expect(deployment_env.fetch('VESTURE_PUBLIC_ORIGIN')).to eq(
      'name' => 'VESTURE_PUBLIC_ORIGIN',
      'value' => 'https://vesture.eyrie',
    )
  end
end
