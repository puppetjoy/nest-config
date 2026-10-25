require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::puppet::deploy' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('compiler-deploy-spec-') }

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  def inspect_command(namespace)
    "kubectl get deployment -n #{namespace} puppet-puppetserver -o 'jsonpath={.spec.template.spec.containers[0].volumeMounts[?(@.name==\"compiler-snapshots\")].name}'"
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  it 'refuses a frozen compiler before r10k writes or environment-cache mutation' do
    allow_any_command.not_be_called
    expect_command(inspect_command('test')).always_return('stdout' => 'compiler-snapshots')
    result = run_plan('nest::puppet::deploy', 'backend' => 'test')
    expect(result.ok?).to be(false)
    expect(result.value.to_s).to include('Immutable compiler selected')
  end

  it 'checks all backends before writing either one' do
    allow_any_command.not_be_called
    expect_command(inspect_command('test')).always_return('stdout' => '')
    expect_command(inspect_command('default')).always_return('stdout' => 'compiler-snapshots')
    expect(run_plan('nest::puppet::deploy', 'backend' => 'kubernetes').ok?).to be(false)
  end

  it 'keeps ordinary r10k deployment and cache expiry when no immutable snapshot is selected' do
    allow_any_command.always_return('stdout' => '')
    deploy = 'kubectl exec -n test deploy/puppet-puppetserver -c r10k-code -- /container-entrypoint.sh deploy environment main --config /etc/puppetlabs/puppet/r10k_code.yaml --puppetfile'
    expect_command(deploy).always_return('stdout' => '')
    expect(run_plan('nest::puppet::deploy', 'backend' => 'test').ok?).to be(true)
  end

  it 'routes an existing immutable compiler through checked additive KubeCM rollout, never r10k' do
    allow_any_command.not_be_called
    expect_command(inspect_command('test')).be_called_times(2).always_return('stdout' => 'compiler-snapshots')
    expect_command('python3 scripts/nest-compiler-rollout.py compiler-candidates/candidate.json test rollout-evidence/compiler/test --check').always_return('stdout' => '{}')
    expect_command('python3 scripts/nest-compiler-rollout.py compiler-candidates/candidate.json test rollout-evidence/compiler/test --deploy').always_return('stdout' => '{}')
    expect(run_plan('nest::puppet::deploy', 'backend' => 'test', 'compiler_candidate' => 'compiler-candidates/candidate.json').ok?).to be(true)
  end

  it 'rejects all-environment and non-main immutable deployment before any writer' do
    allow_any_command.not_be_called
    allow_command(inspect_command('test')).always_return('stdout' => 'compiler-snapshots')
    [{ 'environment' => 'other' }, { 'all_environments' => true }].each do |args|
      result = run_plan('nest::puppet::deploy', args.merge('backend' => 'test', 'compiler_candidate' => 'candidate.json'))
      expect(result.ok?).to be(false)
    end
  end

  it 'does not write either backend when the second immutable preflight fails' do
    allow_any_command.not_be_called
    expect_command(inspect_command('test')).always_return('stdout' => 'compiler-snapshots')
    expect_command(inspect_command('default')).always_return('stdout' => 'compiler-snapshots')
    expect_command('python3 scripts/nest-compiler-rollout.py candidate.json test rollout-evidence/compiler/test --check').always_return('stdout' => '{}')
    expect_command('python3 scripts/nest-compiler-rollout.py candidate.json default rollout-evidence/compiler/default --check').error_with('kind' => 'fixture/compiler', 'msg' => 'Unready compiler')
    expect(run_plan('nest::puppet::deploy', 'compiler_candidate' => 'candidate.json').ok?).to be(false)
  end
end
