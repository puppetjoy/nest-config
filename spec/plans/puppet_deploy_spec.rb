require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::puppet::deploy' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('puppet-deploy-spec-') }

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  def deploy_command(namespace)
    "kubectl exec -n #{namespace} deploy/puppet-puppetserver -c r10k-code -- /container-entrypoint.sh deploy environment main --config /etc/puppetlabs/puppet/r10k_code.yaml --puppetfile"
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  it 'deploys ordinary code to test and production with no compiler candidate' do
    allow_any_command.always_return('stdout' => '')
    expect_command(deploy_command('test')).be_called_times(1).always_return('stdout' => '')
    expect_command(deploy_command('default')).be_called_times(1).always_return('stdout' => '')
    expect(run_plan('nest::puppet::deploy', {}).ok?).to be(true)
  end

  it 'expires the native environment cache after r10k succeeds' do
    commands = []
    allow_any_command.return do |targets:, command:, **_options|
      commands << command
      Bolt::ResultSet.new(targets.map do |target|
        Bolt::Result.for_command(target, { 'stdout' => '', 'stderr' => '', 'exit_code' => 0 }, 'command', command, [])
      end)
    end
    expect(run_plan('nest::puppet::deploy', 'backend' => 'test').ok?).to be(true)
    deploy_index = commands.index(deploy_command('test'))
    expire_index = commands.index { |command| command.include?('puppet-admin-api/v1/environment-cache') }
    expect(deploy_index).not_to be_nil
    expect(expire_index).to be > deploy_index
  end

  it 'stops on failed r10k deployment without updating the other backend' do
    allow_any_command.always_return('stdout' => '')
    expect_command(deploy_command('test')).error_with('kind' => 'fixture/r10k', 'msg' => 'Deployment failed')
    expect_command(deploy_command('default')).not_be_called
    expect(run_plan('nest::puppet::deploy', {}).ok?).to be(false)
  end
end
