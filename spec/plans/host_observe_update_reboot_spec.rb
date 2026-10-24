require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::host::observe_update_reboot' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('nest-reboot-observation-spec-') }
  let(:parameters) do
    {
      'target' => 'fixture-host', 'hostname' => 'fixture-host',
      'transaction' => 'fixture-report', 'release' => "sha256:#{'a' * 64}",
      'output_dir' => '/supervisor/reports', 'admission' => { 'path' => '/supervisor/reports/exact.json' },
    }
  end
  let(:context) { parameters.reject { |key, _value| key == 'target' } }
  let(:command) { 'nest reset status fixture-report --format=json' }
  let(:receipt) do
    {
      'transaction' => parameters['transaction'], 'release' => parameters['release'],
      'hostname' => parameters['hostname'], 'readback_verified' => true,
      'read_only' => true, 'submission_outcome' => 'unknown', 'target_boot_observed' => false,
      'resubmission_allowed' => false, 'execution_requested' => false, 'acceptance_recorded' => false,
    }
  end

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  ['not_attempted', 'unknown', 'returned_success', 'returned_failure'].each do |outcome|
    it "retains #{outcome} without submitting or accepting" do
      calls = []
      expect_task('nest::retain_update_reboot_observation').with_params(context.merge('action' => 'check')).return do |targets:, **_options|
        calls << 'check'
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.new(target, value: { 'admission_readback_verified' => true }) })
      end
      expect_command(command).with_targets('fixture-host').return do |targets:, **_options|
        calls << 'status'
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => '{}', 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
      end
      expect_task('nest::retain_update_reboot_observation').with_targets('localhost').with_params(context.merge('action' => 'retain', 'report' => '{}')).return do |targets:, **_options|
        calls << 'retain'
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.new(target, value: receipt.merge('submission_outcome' => outcome)) })
      end

      result = run_plan('nest::host::observe_update_reboot', parameters)

      expect(result.ok?).to be(true)
      expect(result.value['submission_outcome']).to eq(outcome)
      expect(result.value['execution_requested']).to be(false)
      expect(calls).to eq(['check', 'status', 'retain'])
    end
  end

  it 'refuses absent or corrupt admission before contacting the host' do
    expect_task('nest::retain_update_reboot_observation').with_params(context.merge('action' => 'check')).error_with('kind' => 'fixture', 'msg' => 'Missing admission')
    expect_command(command).not_be_called

    expect(run_plan('nest::host::observe_update_reboot', parameters).ok?).to be(false)
  end

  it 'does not retry a transport failure, submit a reboot or publish invented status' do
    expect_task('nest::retain_update_reboot_observation').with_params(context.merge('action' => 'check')).always_return('admission_readback_verified' => true)
    expect_command(command).always_return(exit_code: 3, stderr: 'Disconnected')
    expect_task('nest::retain_update_reboot_observation').with_params(context.merge('action' => 'retain', 'report' => '{}')).not_be_called

    expect(run_plan('nest::host::observe_update_reboot', parameters).ok?).to be(false)
  end

  [
    { 'readback_verified' => false }, { 'transaction' => 'wrong' }, { 'hostname' => 'wrong' },
    { 'release' => "sha256:#{'b' * 64}" }, { 'read_only' => false }, { 'execution_requested' => true },
    { 'acceptance_recorded' => true }, { 'resubmission_allowed' => true }, { 'submission_outcome' => 'unknown_guess' },
    { 'target_boot_observed' => nil }, { 'target_boot_observed' => true, 'submission_outcome' => 'not_attempted' }
  ].each do |change|
    it "refuses an unbound or contradictory receipt #{change.inspect}" do
      expect_task('nest::retain_update_reboot_observation').with_params(context.merge('action' => 'check')).always_return('admission_readback_verified' => true)
      expect_command(command).always_return(stdout: '{}')
      expect_task('nest::retain_update_reboot_observation').with_params(context.merge('action' => 'retain', 'report' => '{}')).always_return(receipt.merge(change))

      result = run_plan('nest::host::observe_update_reboot', parameters)

      expect(result.ok?).to be(false)
      expect(result.value.kind).to eq('nest/update-reboot-observation-retention')
    end
  end

  [[], ['fixture-host', 'other'], ['fixture-console'], ['fixture-console.example']].each do |targets|
    it "rejects unsupported targets #{targets.inspect} before host contact" do
      expect_task('nest::retain_update_reboot_observation').not_be_called
      expect_command(command).not_be_called

      expect(run_plan('nest::host::observe_update_reboot', parameters.merge('target' => targets)).ok?).to be(false)
    end
  end
end
