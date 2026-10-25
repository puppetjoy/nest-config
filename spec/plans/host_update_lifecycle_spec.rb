require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::host::update_lifecycle' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('nest-lifecycle-spec-') }
  let(:names) { ['fixture-good', 'fixture-other'] }
  let(:observations) { names.to_h { |name| [name, { 'transaction' => name }] } }
  let(:policy) { { 'lifecycle' => { 'controller' => 'fixture-controller', 'retention' => 'keep_backups_and_origins_until_release_retired' } } }
  let(:bound) { { 'waves' => [names], 'policy_sha256' => 'b' * 64, 'release' => "sha256:#{'a' * 64}", 'backup_requirements' => names.to_h { |name| [name, []] } } }
  let(:params) { { 'targets' => names, 'policy' => policy, 'observations' => observations, 'output_dir' => '/fixture' } }
  let(:events) { [] }
  let(:submitted) { {} }
  let(:restarted) { false }
  let(:boot_observed) { true }

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  def admission(name)
    { 'transaction' => name, 'hostname' => name, 'reboot_eligible' => true, 'readback_verified' => true }
  end

  before :each do
    allow_command('sleep 5')
    allow_task('nest::update_controller').always_return('controller_observed' => true)
    allow_task('nest::update_lifecycle').return do |targets:, params:, **_options|
      name = params['host']
      value = case params['action']
              when 'inputs' then bound
              when 'read'
                if params['step'] == 'reboot' && restarted
                  { 'complete' => true, 'intent' => true, 'receipt' => admission(name) }
                else
                  { 'complete' => false, 'intent' => false }
                end
              when 'begin'
                events << "begin:#{name}:#{params['step']}"
                { 'intent_retained' => true }
              else { 'readback_verified' => true }
              end
      Bolt::ResultSet.new(targets.map { |target| Bolt::Result.new(target, value: value) })
    end
    allow_plan('nest::host::check_update_reboot').return do |params:, **_options|
      events << "admit:#{params['hostname']}"
      Bolt::PlanResult.new(admission(params['hostname']), 'success')
    end
    allow_plan('nest::host::observe_update_reboot').return do |params:, **_options|
      name = params['hostname']
      events << "observe:#{name}"
      Bolt::PlanResult.new({ 'submission_outcome' => (restarted || submitted[name]) ? 'unknown' : 'not_attempted',
                             'target_boot_observed' => boot_observed && (restarted || submitted[name]) == true }, 'success')
    end
    names.each do |name|
      allow_command("nest reset reboot #{name} --execute --format=json").with_targets(name).return do |targets:, command:, **_options|
        submitted[name] = true
        events << "reboot:#{name}"
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => '', 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
      end
    end
    allow_plan('nest::host::update_acceptance').return do |params:, **_options|
      events << "accept:#{params['target']}"
      Bolt::PlanResult.new({ 'accepted' => true }, 'success')
    end
    allow_plan('nest::host::update_finalize').return do |params:, **_options|
      events << "finalize:#{params['target']}"
      Bolt::PlanResult.new({ 'state' => 'finalized' }, 'success')
    end
  end

  it 'previews by default without dispatch, reset, submission or acceptance' do
    expect_task('nest::update_controller').not_be_called
    expect_plan('nest::host::update_acceptance').not_be_called
    allow_any_command.not_be_called

    result = run_plan('nest::host::update_lifecycle', params)

    expect(result.ok?).to be(true)
    expect(result.value['execution_requested']).to be(false)
    expect(events.sort).to eq(names.map { |name| "admit:#{name}" }.sort)
  end

  it 'admits every preparation before any submission and finalizes only after acceptance' do
    result = run_plan('nest::host::update_lifecycle', params.merge('execute' => true))

    expect(result.ok?).to be(true), result.value.to_s
    names.each do |name|
      expect(events.index("admit:#{name}")).to be < events.index('reboot:fixture-good')
      expect(events.index("begin:#{name}:submit")).to be < events.index("reboot:#{name}")
      expect(events.index("accept:#{name}")).to be < events.index("finalize:#{name}")
    end
    expect(result.value['host_count']).to eq(2)
  end

  it 'never submits any reboot when a preparation is failed or unknown' do
    expect_plan('nest::host::check_update_reboot').with_params('target' => 'fixture-other', 'transaction' => 'fixture-other',
      'release' => bound['release'], 'hostname' => 'fixture-other', 'output_dir' => '/fixture').error_with('kind' => 'fixture', 'msg' => 'Not prepared')
    expect_plan('nest::host::update_acceptance').not_be_called
    allow_any_command.not_be_called

    expect(run_plan('nest::host::update_lifecycle', params.merge('execute' => true)).ok?).to be(false)
  end

  context 'after external controller restart' do
    let(:restarted) { true }

    it 'reopens original admissions and observes native intent without resubmission' do
      expect_plan('nest::host::check_update_reboot').not_be_called
      allow_any_command.not_be_called

      result = run_plan('nest::host::update_lifecycle', params.merge('execute' => true))

      expect(result.ok?).to be(true), result.value.to_s
      expect(events.count { |event| event.start_with?('observe:') }).to eq(2)
    end
  end

  context 'before actual target boot is observed' do
    let(:boot_observed) { false }
    let(:bound) { super().merge('waves' => names.zip) }

    it 'halts without accepting or starting a later wave' do
      expect_plan('nest::host::update_acceptance').not_be_called
      expect_plan('nest::host::update_finalize').not_be_called

      result = run_plan('nest::host::update_lifecycle', params.merge('execute' => true))

      expect(result.ok?).to be(false)
      expect(result.value.to_s).to include('Expected target boot is not observed yet')
      expect(events).not_to include('reboot:fixture-other', 'accept:fixture-other')
    end
  end
end
