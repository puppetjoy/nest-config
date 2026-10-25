require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::kubernetes::deploy compiler retention boundary' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('compiler-chart-spec-') }
  let(:params) { { 'service' => 'puppet', 'app' => 'openvox', 'namespace' => 'test', 'chart' => 'openvox/puppetserver', 'version' => '10.1.1', 'init' => false } }
  let(:inspect_command) do
    'kubectl get deployment -n test puppet-puppetserver --ignore-not-found -o \'jsonpath={.spec.template.spec.containers[0].volumeMounts[?(@.name=="compiler-snapshots")].name}\''
  end

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    FileUtils.mkdir_p(File.join(plan_modulepath, 'kubecm/plans'))
    names = ['release', 'chart', 'chart_source', 'deploy', 'hooks', 'namespace', 'remove_resources', 'remove_patches',
             'render_to', 'repo_url', 'version', 'wait', 'sleep', 'subcharts']
    arguments = names.map { |name| "Any $#{name} = undef" }.join(', ')
    File.write(File.join(plan_modulepath, 'kubecm/plans/deploy.pp'), "plan kubecm::deploy (#{arguments}) { fail('Inert test boundary must be mocked') }")
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  it 'leaves a mutable or absent compiler on the normal KubeCM path' do
    allow_any_command.not_be_called
    allow_any_plan.not_be_called
    expect_command(inspect_command).always_return('stdout' => '')
    expect_plan('kubecm::deploy').always_return({})
    expect(run_plan('nest::kubernetes::deploy', params).ok?).to be(true)
  end

  it 'keeps rendering nonmutating without recursively inspecting or rendering' do
    allow_any_command.not_be_called
    allow_any_plan.not_be_called
    expect_plan('kubecm::deploy').return do |params:, **_options|
      expect(params['render_to']).to eq('fixture.yaml')
      Bolt::PlanResult.new({}, 'success')
    end
    expect(run_plan('nest::kubernetes::deploy', params.merge('render_to' => 'fixture.yaml')).ok?).to be(true)
  end

  it 'renders a frozen compiler and guards its retained set before the normal Helm write' do
    allow_any_command.not_be_called
    allow_any_plan.not_be_called
    expect_command(inspect_command).always_return('stdout' => 'compiler-snapshots')
    expect_command('umask 077; mkdir -p rollout-evidence && mktemp -d rollout-evidence/compiler-chart.XXXXXXXX').always_return('stdout' => "rollout-evidence/compiler-chart.fixture\n")
    expect_plan('nest::kubernetes::deploy').return do |params:, **_options|
      expect(params).to include('render_to' => 'rollout-evidence/compiler-chart.fixture/rendered.yaml', 'init' => false)
      Bolt::PlanResult.new({}, 'success')
    end
    expect_command('python3 scripts/nest-compiler-rollout.py --guard-chart test rollout-evidence/compiler-chart.fixture/rendered.yaml').always_return('stdout' => '{}')
    expect_plan('kubecm::deploy').always_return({})
    expect(run_plan('nest::kubernetes::deploy', params).ok?).to be(true)
  end

  it 'refuses the actual Helm write when stale Hiera would discard a CI successor' do
    allow_any_command.not_be_called
    allow_any_plan.not_be_called
    expect_command(inspect_command).always_return('stdout' => 'compiler-snapshots')
    expect_command('umask 077; mkdir -p rollout-evidence && mktemp -d rollout-evidence/compiler-chart.XXXXXXXX').always_return('stdout' => "rollout-evidence/compiler-chart.fixture\n")
    expect_plan('nest::kubernetes::deploy').always_return({})
    expect_command('python3 scripts/nest-compiler-rollout.py --guard-chart test rollout-evidence/compiler-chart.fixture/rendered.yaml').error_with(
      'kind' => 'fixture/retention', 'msg' => 'Retained identity absent',
    )
    expect(run_plan('nest::kubernetes::deploy', params).ok?).to be(false)
  end
end
