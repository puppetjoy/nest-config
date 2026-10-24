require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::host::check_update_capacity' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('nest-plan-spec-') }
  let(:release) { "sha256:#{'a' * 64}" }
  let(:inputs) { { 'transaction' => 'fixture', 'root_generation' => '/fixture/root', 'capacity_policy' => '/fixture/capacity.json' } }
  let(:params) { { 'target' => 'fixture-host', 'release' => release, 'inputs' => inputs, 'output_dir' => '/fixture/reports' } }
  let(:command) { "nest reset --plan --release #{release} --root-generation /fixture/root --capacity-policy /fixture/capacity.json --format=json" }

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  it 'runs only the native read-only planner and retains its stdout on the supervisor' do
    expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => 'fixture', 'release' => release, 'hostname' => 'fixture-host', 'output_dir' => '/fixture/reports')
    expect_command(command).with_targets('fixture-host').always_return('stdout' => 'fixture plan')
    expected = { 'report' => 'fixture plan', 'hostname' => 'fixture-host', 'release' => release, 'inputs' => inputs, 'output_dir' => '/fixture/reports' }
    expect_task('nest::retain_update_preflight').with_targets('localhost').with_params(expected).always_return('capacity_admitted' => true, 'readback_verified' => true)
    result = run_plan('nest::host::check_update_capacity', params)
    expect(result.ok?).to be(true)
    expect(result.value).to eq('capacity_admitted' => true, 'readback_verified' => true)
  end

  it 'does not contact the host when the supervisor destination is invalid' do
    expect_task('nest::retain_update_report').error_with('kind' => 'fixture/directory', 'msg' => 'Unavailable directory')
    allow_any_command.not_be_called
    expect_task('nest::retain_update_preflight').not_be_called
    expect(run_plan('nest::host::check_update_capacity', params).ok?).to be(false)
  end

  ['preflight', 'initiation'].each do |stage|
    it "passes the exact optional preparation association at #{stage}" do
      binding = { 'transaction' => 'fixture', 'policy_sha256' => 'e' * 64, 'stage' => stage }
      allow_task('nest::retain_update_report')
      expect_command(command).with_targets('fixture-host').always_return('stdout' => 'fixture plan')
      expected = { 'report' => 'fixture plan', 'hostname' => 'fixture-host', 'release' => release,
                   'inputs' => inputs, 'output_dir' => '/fixture/reports', 'binding' => binding }
      expect_task('nest::retain_update_preflight').with_params(expected).always_return('preparation' => binding)
      expect(run_plan('nest::host::check_update_capacity', params.merge('binding' => binding)).value).to eq('preparation' => binding)
    end
  end

  [{}, { 'transaction' => 'other', 'policy_sha256' => 'e' * 64, 'stage' => 'preflight' },
   { 'transaction' => 'fixture', 'policy_sha256' => 'invalid', 'stage' => 'preflight' },
   { 'transaction' => 'fixture', 'policy_sha256' => 'e' * 64, 'stage' => 'accepted' },
   { 'transaction' => 'fixture', 'policy_sha256' => 'e' * 64, 'stage' => 'preflight', 'extra' => true }].each do |binding|
    it "refuses malformed association before host contact: #{binding.keys.join(', ')}" do
      allow_any_command.not_be_called
      expect_task('nest::retain_update_report').not_be_called
      expect_task('nest::retain_update_preflight').not_be_called
      expect(run_plan('nest::host::check_update_capacity', params.merge('binding' => binding)).ok?).to be(false)
    end
  end

  it 'does not retain or replay a native planner refusal' do
    allow_task('nest::retain_update_report')
    expect_command(command).return do |targets:, command:, **_options|
      Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => 'refused', 'stderr' => '', 'exit_code' => 3 }, 'command', command, []) })
    end
    expect_task('nest::retain_update_preflight').not_be_called
    expect(run_plan('nest::host::check_update_capacity', params).ok?).to be(false)
  end

  it 'does not replay when returned admission fails validation or retention' do
    allow_task('nest::retain_update_report')
    expect_command(command).always_return('stdout' => 'malformed')
    expect_task('nest::retain_update_preflight').error_with('kind' => 'fixture/report', 'msg' => 'Invalid admission')
    expect(run_plan('nest::host::check_update_capacity', params).ok?).to be(false)
  end

  [['fixture-host', 'other'], ['fixture-console'], ['fixture-console.nest']].each do |selection|
    it "refuses invalid capacity target selection #{selection} without any host action" do
      allow_any_command.not_be_called
      expect_task('nest::retain_update_report').not_be_called
      expect(run_plan('nest::host::check_update_capacity', params.merge('target' => selection)).ok?).to be(false)
    end
  end
end
