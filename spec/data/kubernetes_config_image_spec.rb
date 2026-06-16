require 'spec_helper'

RSpec.describe 'Kubernetes config image references' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:common_yaml) { File.read(File.join(repo_root, 'data/kubernetes/common.yaml')) }
  let(:honcho_yaml) { File.read(File.join(repo_root, 'data/kubernetes/app/honcho.yaml')) }
  let(:ci_yaml) { File.read(File.join(repo_root, '.gitlab-ci.yml')) }

  it 'defines the Nest config image with an explicit tag' do
    expect(common_yaml).to include(%(config_image: "%{lookup('config_registry')}/nest/config/main:latest"))
  end

  it 'uses the tagged config image alias for the shared backup CronJob' do
    expect(common_yaml).to match(%r{kind: CronJob.*image: "%\{lookup\('config_image'\)\}"}m)
    expect(common_yaml).not_to include(%(image: "%{lookup('config_registry')}/nest/config/main"))
  end

  it 'uses the tagged config image alias for Honcho init jobs' do
    expect(honcho_yaml).to include(%(image: "%{lookup('config_image')}"))
    expect(honcho_yaml).not_to include(%(image: "%{lookup('config_registry')}/nest/config/main"))
  end

  it 'publishes the config manifest with the explicit latest tag used by jobs' do
    expect(ci_yaml).to include('"${CI_REGISTRY}/${IMAGE}:latest"')
    expect(ci_yaml).to include('"registry.eyrie/${IMAGE}:latest"')
  end
end
