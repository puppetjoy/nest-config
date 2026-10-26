require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::host::update_acceptance' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('nest-acceptance-spec-') }
  let(:boot_id) { '22345678-1234-1234-1234-123456789abc' }
  let(:status) { { 'observation' => { 'boot_id' => boot_id } }.to_json }
  let(:events) { [] }
  let(:ambiguous) { false }
  let(:settings) { { 'certname' => 'fixture.nest', 'endpoints' => [], 'canaries' => [{ 'name' => 'smoke', 'command' => ['/usr/bin/true'] }] } }
  let(:policy) { { 'config_source' => 'a' * 40, 'lifecycle' => { 'acceptance' => { 'fixture-host' => settings } } } }
  let(:params) { { 'target' => 'fixture-host', 'policy' => policy, 'observations' => { 'fixture-host' => { 'transaction' => 'fixture' } }, 'output_dir' => '/fixture' } }

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  before :each do
    allow_command('nest reset status fixture --format=json').always_return(stdout: status)
    allow_task('nest::update_lifecycle').return do |targets:, params:, **_options|
      events << "#{params['action']}:#{params['step']}"
      value = case params['action']
              when 'inputs' then { 'release' => "sha256:#{'a' * 64}" }
              when 'read' then { 'complete' => false, 'intent' => ambiguous }
              when 'boot' then { 'hostname' => 'fixture-host' }
              when 'evidence' then { 'evidence' => { 'kind' => 'reset_acceptance_evidence' }, 'readback_verified' => true }
              else { 'readback_verified' => true }
              end
      Bolt::ResultSet.new(targets.map { |target| Bolt::Result.new(target, value: value) })
    end
    allow_plan('nest::host::update_catalog').return do |params:, **_options|
      events << 'catalog'
      expect(params['expectations']).to include('boot_id' => boot_id, 'configuration_version' => 'a' * 40)
      Bolt::PlanResult.new({ 'result' => 'pass', 'retained_report' => { 'readback_verified' => true } }, 'success')
    end
    allow_plan('nest::host::update_health').always_return('retained_report' => { 'readback_verified' => true })
    allow_command('/usr/bin/true').always_return(stdout: 'not retained')
    allow_task('nest::update_accept').always_return('accepted' => true)
    allow_task('nest::retain_update_report').always_return('cli_accepted' => true, 'observation_retained' => true)
  end

  it 'collects normal main, health and bracketed canary evidence before native acceptance' do
    result = run_plan('nest::host::update_acceptance', params)

    expect(result.ok?).to be(true), result.value.to_s
    expect(events.index('begin:catalog')).to be < events.index('catalog')
    expect(events.index('complete:catalog')).to be < events.index('evidence:')
    expect(events).not_to include('begin:health')
    expect(events).to include('complete:health')
    expect(result.value['accepted']['cli_accepted']).to be(true)
  end

  context 'after a lost catalog result' do
    let(:ambiguous) { true }

    it 'does not replay main apply, canaries or acceptance' do
      expect_plan('nest::host::update_catalog').not_be_called
      expect_plan('nest::host::update_health').not_be_called
      expect_task('nest::update_accept').not_be_called
      expect_command('/usr/bin/true').not_be_called

      result = run_plan('nest::host::update_acceptance', params)

      expect(result.ok?).to be(false)
      expect(result.value.to_s).to include('Prior catalog outcome is ambiguous')
    end
  end
end
