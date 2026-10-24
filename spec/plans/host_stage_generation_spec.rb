require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::host::stage_generation' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('nest-plan-spec-') }
  let(:policy) { { 'hostname' => 'fixture-host' } }
  let(:manifest) { { 'kind' => 'fixture-manifest' } }
  let(:output_dir) { '/persistent/reports' }
  let(:receipt) { { 'kind' => 'nest_generation_retention_receipt', 'readback_verified' => true } }
  let(:report) do
    { 'kind' => 'nest_generation_transfer_report', 'schema' => 1, 'policy' => policy,
      'read_only' => true, 'sealed' => false, 'reset_authorized' => false }
  end

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    allow_task('nest::update_generation_binding').always_return('reset_authorized' => false)
    allow_task('nest::retain_generation_report').always_return(receipt)
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  def command(check)
    "python3 /usr/libexec/nest/transfer-generation.py '#{policy.to_json}'#{check ? ' --check' : ''}"
  end

  it 'defaults to exact inventory-backed read-only admission' do
    expect_command(command(true)).with_targets('fixture-host').always_return('stdout' => report.to_json)
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest)

    expect(result.ok?).to be(true)
    expect(result.value).to eq(report)
  end

  it 'refuses a missing manifest before any target command' do
    allow_any_command.not_be_called
    expect(run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy).ok?).to be(false)
  end

  it 'refuses manifest binding failure before any target command' do
    allow_any_command.not_be_called
    binding = { 'manifest' => manifest, 'policies' => { 'fixture-host' => policy } }
    expect_task('nest::update_generation_binding').with_targets('localhost').with_params(binding).error_with('kind' => 'fixture/binding', 'msg' => 'Wrong root')
    expect(run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest).ok?).to be(false)
  end

  it 'requires explicit check=false to invoke the transfer path' do
    transferred = report.merge('read_only' => false, 'sealed' => true)
    expect_command(command(false)).with_targets('fixture-host').always_return('stdout' => transferred.to_json)
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'check' => false, 'output_dir' => output_dir)

    expect(result.ok?).to be(true)
    expect(result.value).to eq('report' => transferred, 'retained' => receipt)
  end

  it 'refuses transfer without supervisor retention before any target command' do
    allow_any_command.not_be_called
    expect(run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'check' => false).ok?).to be(false)
  end

  it 'refuses failed directory preflight before any target command' do
    expect_task('nest::retain_generation_report').with_params('output_dir' => output_dir).error_with('kind' => 'fixture/path', 'msg' => 'Missing output directory')
    allow_any_command.not_be_called
    expect(run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'output_dir' => output_dir).ok?).to be(false)
  end

  it 'retains exact native stdout on localhost after the one target command' do
    expect_task('nest::retain_generation_report').with_targets('localhost').with_params('output_dir' => output_dir).always_return('read_only' => true)
    expect_command(command(true)).with_targets('fixture-host').always_return('stdout' => report.to_json)
    expect_task('nest::retain_generation_report').with_targets('localhost').with_params(
      'output_dir' => output_dir, 'report' => report.to_json, 'policy' => policy, 'check' => true, 'verify_only' => false,
    ).always_return(receipt)
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'output_dir' => output_dir)

    expect(result.ok?).to be(true)
    expect(result.value).to eq('report' => report, 'retained' => receipt)
  end

  it 'reports retention failure without replaying successful transfer' do
    transferred = report.merge('read_only' => false, 'sealed' => true)
    expect_command(command(false)).with_targets('fixture-host').always_return('stdout' => transferred.to_json)
    expect_task('nest::retain_generation_report').with_params(
      'output_dir' => output_dir, 'report' => transferred.to_json, 'policy' => policy, 'check' => false, 'verify_only' => false,
    ).error_with('kind' => 'fixture/retention', 'msg' => 'Failed publication; never replay')
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'check' => false, 'output_dir' => output_dir)

    expect(result.ok?).to be(false)
  end

  it 'verifies a sealed local generation without selecting the transfer path' do
    verified = report.merge('kind' => 'nest_generation_verification_report', 'sealed' => true, 'reset_capacity_admitted' => false)
    expect_command("#{command(false)} --verify").with_targets('fixture-host').always_return('stdout' => verified.to_json)
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'verify_only' => true)

    expect(result.ok?).to be(true)
    expect(result.value).to eq(verified)
  end

  it 'passes exact preparation context through preflight and sealed verification retention' do
    binding = { 'transaction' => 'fixture', 'policy_sha256' => 'd' * 64, 'stage' => 'initiation' }
    verified = report.merge('kind' => 'nest_generation_verification_report', 'sealed' => true, 'reset_capacity_admitted' => false)
    bound_receipt = receipt.merge('preparation' => binding)
    expect_task('nest::retain_generation_report').with_params('output_dir' => output_dir, 'binding' => binding).always_return('read_only' => true)
    expect_command("#{command(false)} --verify").with_targets('fixture-host').always_return('stdout' => verified.to_json)
    expect_task('nest::retain_generation_report').with_params(
      'output_dir' => output_dir, 'binding' => binding, 'report' => verified.to_json, 'policy' => policy, 'check' => true, 'verify_only' => true,
    ).always_return(bound_receipt)
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest,
                      'verify_only' => true, 'output_dir' => output_dir, 'binding' => binding)

    expect(result.ok?).to be(true)
    expect(result.value['retained']).to eq(bound_receipt)
  end

  it 'refuses failed binding preflight before any native command' do
    binding = { 'transaction' => 'bad id' }
    expect_task('nest::retain_generation_report').with_params('output_dir' => output_dir, 'binding' => binding).error_with('kind' => 'fixture/context', 'msg' => 'Invalid context')
    allow_any_command.not_be_called
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest,
                      'verify_only' => true, 'output_dir' => output_dir, 'binding' => binding)

    expect(result.ok?).to be(false)
  end

  [{}, { 'verify_only' => true }, { 'output_dir' => '/persistent/reports' }, { 'check' => false, 'output_dir' => '/persistent/reports' }].each do |options|
    it "refuses preparation context outside retained sealed verification #{options}" do
      allow_any_command.not_be_called
      result = run_plan('nest::host::stage_generation', options.merge('targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'binding' => {}))

      expect(result.ok?).to be(false)
    end
  end

  it 'refuses a retainer that drops the context without replaying native verification' do
    binding = { 'transaction' => 'fixture', 'policy_sha256' => 'd' * 64, 'stage' => 'initiation' }
    verified = report.merge('kind' => 'nest_generation_verification_report', 'sealed' => true, 'reset_capacity_admitted' => false)
    expect_command("#{command(false)} --verify").with_targets('fixture-host').always_return('stdout' => verified.to_json)
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest,
                      'verify_only' => true, 'output_dir' => output_dir, 'binding' => binding)

    expect(result.ok?).to be(false)
  end

  it 'refuses contradictory verification and transfer inputs before any command' do
    allow_any_command.not_be_called
    result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'verify_only' => true, 'check' => false)

    expect(result.ok?).to be(false)
  end

  [
    { 'kind' => 'nest_generation_transfer_report' },
    { 'read_only' => false },
    { 'sealed' => false },
    { 'reset_authorized' => true },
    { 'reset_capacity_admitted' => true },
    { 'reset_capacity_admitted' => nil },
  ].each do |change|
    it "refuses contradictory sealed verification result #{change} without retry" do
      verified = report.merge('kind' => 'nest_generation_verification_report', 'sealed' => true, 'reset_capacity_admitted' => false).merge(change)
      expect_command("#{command(false)} --verify").with_targets('fixture-host').always_return('stdout' => verified.to_json)
      result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest, 'verify_only' => true)

      expect(result.ok?).to be(false)
    end
  end

  ['other', 'fixture-host.nest', 'fixture-console', 'fixture-console.nest', 'control1.nest'].each do |name|
    it "refuses nonmatching or excluded inventory scope #{name} before any command" do
      allow_any_command.not_be_called
      result = run_plan('nest::host::stage_generation', 'targets' => name, 'policy' => policy, 'manifest' => manifest)

      expect(result.ok?).to be(false)
    end
  end

  it 'refuses multiple targets before any command' do
    allow_any_command.not_be_called
    result = run_plan('nest::host::stage_generation', 'targets' => ['fixture-host', 'other'], 'policy' => policy, 'manifest' => manifest)

    expect(result.ok?).to be(false)
  end

  ['fixture-console', 'fixture-console.nest', 'control1.nest'].each do |name|
    it "refuses excluded name #{name} even when the supplied policy agrees" do
      allow_any_command.not_be_called
      result = run_plan('nest::host::stage_generation', 'targets' => name, 'policy' => policy.merge('hostname' => name), 'manifest' => manifest)

      expect(result.ok?).to be(false)
    end
  end

  [
    { 'sealed' => true },
    { 'read_only' => false },
    { 'policy' => { 'hostname' => 'different' } },
    { 'schema' => 2 },
    { 'reset_authorized' => true },
  ].each do |change|
    it "refuses changed or contradictory result #{change} without retry" do
      expect_command(command(true)).with_targets('fixture-host').always_return('stdout' => report.merge(change).to_json)
      result = run_plan('nest::host::stage_generation', 'targets' => 'fixture-host', 'policy' => policy, 'manifest' => manifest)

      expect(result.ok?).to be(false)
    end
  end
end
