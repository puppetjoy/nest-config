require 'spec_helper'
require 'yaml'

RSpec.describe 'OpenVox management boundaries' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:deploy_plan) { File.read(File.join(repo_root, 'plans/puppet/deploy.pp')) }
  let(:bolt_class) { File.read(File.join(repo_root, 'manifests/tool/bolt.pp')) }
  let(:bolt_template) { File.read(File.join(repo_root, 'templates/puppet/bolt-defaults.yaml.epp')) }
  let(:ci) { YAML.safe_load_file(File.join(repo_root, '.gitlab-ci.yml')) }
  let(:delete_plan) { YAML.safe_load_file(File.join(repo_root, 'plans/puppet/delete_node.yaml')) }

  it 'uses the ingress port explicitly instead of Bolt defaulting to the unavailable mTLS port' do
    expect(bolt_class).to include("puppetdb_server_url => 'https://puppetdb.eyrie:443'")
    expect(bolt_class).to include("source => 'puppet:///modules/nest/certs/eyrie.crt'")
    expect(bolt_template).not_to match(%r{^  (cert|key):})
  end

  it 'deploys both OpenVox environments and expires compiler caches without a legacy backend' do
    expect(deploy_plan).to match(%r{\$backend\s+= 'kubernetes'})
    expect(deploy_plan).to include("'both'       => ['test', 'prod']", "'all'        => ['test', 'prod']")
    expect(deploy_plan).to include('puppet-admin-api/v1/environment-cache', '--request DELETE')
    expect(deploy_plan).not_to include('/srv/puppet', "'legacy'", 'puppet-server')
  end

  it 'uses the ordinary OpenVox code deployment plan from CI' do
    expect(ci.fetch('Deploy environment').fetch('script')).to include(
      'export BOLT_PROJECT="$CI_PROJECT_DIR"',
      'bolt plan run nest::puppet::deploy backend=kubernetes environment="$CI_COMMIT_BRANCH"',
    )
    expect(ci.fetch('Deploy environment').fetch('needs')).to eq([{ 'job' => 'Deploy image', 'artifacts' => true }])
    expect(ci.fetch('Deploy environment').fetch('resource_group')).to eq('puppet-code-deployment')
  end

  it 'targets the selected OpenVox authority for explicit node removal' do
    commands = delete_plan.fetch('steps').map { |step| step.fetch('command') }
    expect(commands).to all(include('kubectl exec -n ${namespace} deploy/puppet-puppetserver'))
    expect(commands).to all(satisfy { |command| !command.include?('podman') })
    expect(delete_plan.dig('parameters', 'namespace', 'default')).to eq('default')
  end
end
