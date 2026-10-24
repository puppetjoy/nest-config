require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'nest::host::update' do
  include BoltSpec::Plans

  let(:targets) { ['update-good', 'update-failed'] }
  let(:plan_modulepath) { Dir.mktmpdir('nest-plan-spec-') }

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
    # These tests use Bolt's mock executor, never real host commands/reboots.
    allow_plan('nest::host::reboot')
    allow_plan('nest::puppet::run')
  end

  it 'stops after failed preparation without a legacy resume or reboot' do
    expect_command('nest reset').with_targets(targets).return do |targets:, command:, **_options|
      Bolt::ResultSet.new(targets.map do |target|
        value = { 'stdout' => '', 'stderr' => '', 'exit_code' => (target.name == 'update-failed') ? 1 : 0 }
        Bolt::Result.for_command(target, value, 'command', command, [])
      end)
    end
    expect_plan('nest::host::reboot').not_be_called
    expect_plan('nest::puppet::run').not_be_called

    result = run_plan('nest::host::update', 'targets' => targets, 'reboot' => true)

    expect(result.ok?).to be(false)
  end

  it 'does not reboot by default after successful preparation' do
    expect_command('nest reset').with_targets(targets)
    expect_plan('nest::host::reboot').not_be_called

    expect(run_plan('nest::host::update', 'targets' => targets).ok?).to be(true)
  end

  it 'refuses the legacy controller path instead of bypassing service-aware admission' do
    allow_any_command.not_be_called
    expect_plan('nest::host::reboot').not_be_called
    expect(run_plan('nest::host::update', 'targets' => 'control2', 'reboot' => true).ok?).to be(false)
  end

  ['control1.nest', 'control2.nest', 'control3.nest'].each do |controller|
    [true, false].each do |reset|
      it "refuses the entire legacy selection containing #{controller} with reset=#{reset}" do
        allow_any_command.not_be_called
        expect_plan('nest::host::reboot').not_be_called
        expect_plan('nest::puppet::run').not_be_called

        result = run_plan('nest::host::update', 'targets' => ['update-good', controller], 'reset' => reset, 'reboot' => true)

        expect(result.ok?).to be(false)
      end
    end

    it "refuses noncanonical controller preparation for #{controller} before any task or host action" do
      allow_any_command.not_be_called
      expect_task('nest::update_prepare_inputs').not_be_called
      expect_task('nest::retain_update_report').not_be_called
      expect_plan('nest::kubernetes::check_control_plane_maintenance').not_be_called
      expect_plan('nest::host::reboot').not_be_called

      params = { 'targets' => ['update-good', controller], 'mode' => 'prepare', 'policy' => {}, 'preparation' => {}, 'output_dir' => '/fixture', 'release_manifest' => {} }
      result = run_plan('nest::host::update', params)

      expect(result.ok?).to be(false)
      expect(result.value.kind).to eq('nest/maintenance-scope')
    end
  end

  it 'does not classify a similarly prefixed independent name as a controller' do
    expect_command('nest update').with_targets('control3-extra.nest')

    expect(run_plan('nest::host::update', 'targets' => 'control3-extra.nest', 'reset' => false).ok?).to be(true)
  end

  ['fixture-console', 'fixture-console.nest'].each do |console|
    [true, false].each do |reset|
      it "refuses the entire legacy selection containing #{console} with reset=#{reset} before any host action" do
        allow_any_command.not_be_called
        expect_plan('nest::host::reboot').not_be_called
        expect_plan('nest::puppet::run').not_be_called

        result = run_plan('nest::host::update', 'targets' => ['update-good', console], 'reset' => reset, 'reboot' => true)

        expect(result.ok?).to be(false)
      end
    end
  end

  it 'reboots only after all requested preparations succeed' do
    expect_command('nest update').with_targets(targets)
    expect_plan('nest::host::reboot').with_params('targets' => targets)
    expect_plan('nest::puppet::run').with_params('targets' => targets)

    expect(run_plan('nest::host::update', 'targets' => targets, 'reset' => false, 'reboot' => true).ok?).to be(true)
  end

  it 'resolves inventory names and invokes only the supervisor wave planner in plan mode' do
    policy = { 'schema' => 1, 'kind' => 'nest_update_wave_policy' }
    planned = { 'schema' => 1, 'kind' => 'nest_update_wave_plan', 'execution_authorized' => false, 'reboot_eligible' => [] }
    expect_task('nest::update_wave_plan').with_targets('localhost').with_params('policy' => policy, 'targets' => targets).always_return(planned)
    expect_command('nest reset').not_be_called
    expect_command('nest update').not_be_called
    expect_plan('nest::host::reboot').not_be_called
    expect_plan('nest::puppet::run').not_be_called

    result = run_plan('nest::host::update', 'targets' => targets, 'mode' => 'plan', 'policy' => policy)

    expect(result.ok?).to be(true)
    expect(result.value).to eq(planned)
  end

  [
    { 'mode' => 'plan' },
    { 'mode' => 'plan', 'policy' => {}, 'reboot' => true },
    { 'mode' => 'plan', 'policy' => {}, 'reset' => false },
    { 'policy' => {} },
  ].each do |options|
    it "refuses incompatible wave options #{options} without any host action" do
      expect_command('nest reset').not_be_called
      expect_command('nest update').not_be_called
      expect_task('nest::update_wave_plan').not_be_called
      expect_plan('nest::host::reboot').not_be_called
      expect_plan('nest::puppet::run').not_be_called

      expect(run_plan('nest::host::update', options.merge('targets' => targets)).ok?).to be(false)
    end
  end

  it 'does not fall through to execution when policy validation fails' do
    expect_task('nest::update_wave_plan').with_targets('localhost').error_with('kind' => 'nest/update-wave-policy', 'msg' => 'Invalid policy')
    expect_command('nest reset').not_be_called
    expect_plan('nest::host::reboot').not_be_called

    expect(run_plan('nest::host::update', 'targets' => targets, 'mode' => 'plan', 'policy' => {}).ok?).to be(false)
  end

  context 'read-only native observation' do
    let(:inputs) { { 'update-good' => { 'transaction' => 'good' }, 'update-failed' => { 'transaction' => 'failed' } } }
    let(:bound) do
      { 'release' => "sha256:#{'a' * 64}", 'policy_sha256' => 'b' * 64, 'inputs' => inputs,
        'commands' => { 'update-good' => ['nest', 'reset', 'status', 'good', '--format=json'], 'update-failed' => ['nest', 'reset', 'status', 'failed', '--format=json'] },
        'waves' => [['update-good'], ['update-failed']] }
    end
    let(:params) { { 'targets' => targets, 'mode' => 'observe', 'policy' => {}, 'observations' => inputs, 'output_dir' => '/fixture' } }
    let(:scope_receipt) do
      { 'kind' => 'nest_update_scope_index', 'mode' => params['mode'], 'policy_sha256' => bound['policy_sha256'],
        'readback_verified' => true, 'reboot_eligible' => [], 'execution_authorized' => false, 'acceptance_recorded' => false }
    end

    before :each do
      allow_task('nest::retain_update_scope').with_targets('localhost').always_return(scope_receipt)
      expect_task('nest::update_observe_inputs').with_targets('localhost').always_return(bound)
      expect_task('nest::update_prepare_inputs').not_be_called
      expect_plan('nest::host::reboot').not_be_called
      expect_plan('nest::puppet::run').not_be_called
      expect_command('nest reset').not_be_called
    end

    def expect_observation_preflight
      { 'update-good' => 'good', 'update-failed' => 'failed' }.each do |host, id|
        expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => id, 'release' => bound['release'], 'hostname' => host, 'output_dir' => '/fixture')
      end
    end

    def scope_context
      { 'mode' => params['mode'], 'policy' => params['policy'], 'targets' => targets, 'observations' => inputs, 'output_dir' => '/fixture' }
    end

    it 'retains observed stopped and prepared states without mutation or reboot eligibility' do
      checked = false
      expect_task('nest::retain_update_scope').with_params(scope_context.merge('action' => 'check')).return do |targets:, **_options|
        checked = true
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.new(target, value: { 'scope_checked' => true }) })
      end
      expect_observation_preflight
      { 'update-good' => 'good', 'update-failed' => 'failed' }.each do |host, id|
        expect_command("nest reset status #{id} --format=json").with_targets(host).return do |targets:, command:, **_options|
          expect(checked).to be(true)
          Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => "#{id} status", 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
        end
        retain_params = { 'report' => "#{id} status", 'transaction' => id, 'release' => bound['release'], 'hostname' => host, 'output_dir' => '/fixture' }
        expect_task('nest::retain_update_report').with_params(retain_params).always_return('state' => 'stopped', 'observation_retained' => true)
      end
      waves = [[{ 'state' => 'stopped', 'observation_retained' => true, 'backup_verification' => [], 'generation_verification' => nil }]] * 2
      expect_task('nest::retain_update_scope').with_params(scope_context.merge('action' => 'retain', 'waves' => waves)).always_return(scope_receipt)

      result = run_plan('nest::host::update', params)

      expect(result.ok?).to be(true)
      expect(result.value['kind']).to eq('nest_update_observation')
      expect(result.value['reboot_eligible']).to eq([])
      expect(result.value['acceptance_recorded']).to be(false)
      expect(result.value['retained_scope']).to eq(scope_receipt)
    end

    it 'refuses a bad scope destination before contacting any host' do
      expect_task('nest::retain_update_scope').with_params(scope_context.merge('action' => 'check')).error_with('kind' => 'fixture/scope', 'msg' => 'Missing destination')
      allow_any_command.not_be_called

      expect(run_plan('nest::host::update', params).ok?).to be(false)
    end

    [
      { 'readback_verified' => false }, { 'policy_sha256' => 'a' * 64 }, { 'mode' => 'prepare' },
      { 'execution_authorized' => true }, { 'acceptance_recorded' => true }, { 'reboot_eligible' => ['update-good'] }
    ].each do |change|
      it "refuses a changed scope receipt #{change.inspect} without replaying observations" do
        expect_observation_preflight
        { 'update-good' => 'good', 'update-failed' => 'failed' }.each do |host, id|
          expect_command("nest reset status #{id} --format=json").with_targets(host).be_called_times(1).always_return('stdout' => "#{id} status")
          expect_task('nest::retain_update_report').with_params('report' => "#{id} status", 'transaction' => id, 'release' => bound['release'], 'hostname' => host,
                                                              'output_dir' => '/fixture').always_return('observation_retained' => true)
        end
        waves = [[{ 'observation_retained' => true, 'backup_verification' => [], 'generation_verification' => nil }]] * 2
        expect_task('nest::retain_update_scope').with_params(scope_context.merge('action' => 'retain', 'waves' => waves)).always_return(scope_receipt.merge(change))

        result = run_plan('nest::host::update', params)

        expect(result.ok?).to be(false)
        expect(result.value.kind).to eq('nest/update-scope-retention')
      end
    end

    it 'refuses a historical export lacking live observation without continuing' do
      expect_observation_preflight
      expect_command('nest reset status good --format=json').always_return('stdout' => 'historical report')
      retain_params = { 'report' => 'historical report', 'transaction' => 'good', 'release' => bound['release'], 'hostname' => 'update-good', 'output_dir' => '/fixture' }
      expect_task('nest::retain_update_report').with_params(retain_params).always_return('state' => 'prepared', 'observation_retained' => false)
      expect_command('nest reset status failed --format=json').not_be_called

      expect(run_plan('nest::host::update', params).ok?).to be(false)
    end
  end

  [
    { 'mode' => 'observe', 'policy' => {}, 'output_dir' => '/fixture' },
    { 'mode' => 'observe', 'policy' => {}, 'observations' => {}, 'preparation' => {}, 'output_dir' => '/fixture' },
    { 'mode' => 'observe', 'policy' => {}, 'observations' => {}, 'output_dir' => '/fixture', 'reboot' => true },
    { 'mode' => 'plan', 'policy' => {}, 'observations' => {} },
    { 'observations' => {} },
  ].each do |options|
    it "refuses incompatible observation options #{options} before host action" do
      expect_task('nest::update_observe_inputs').not_be_called
      expect_task('nest::update_prepare_inputs').not_be_called
      expect_command('nest reset').not_be_called
      expect_plan('nest::host::reboot').not_be_called

      expect(run_plan('nest::host::update', options.merge('targets' => targets)).ok?).to be(false)
    end
  end

  context 'explicit native preparation' do
    ['legacy', 'plan', 'observe'].each do |mode|
      it "refuses release manifest supplied to #{mode} before tasks or commands" do
        allow_any_command.not_be_called
        expect_task('nest::update_generation_binding').not_be_called
        expect(run_plan('nest::host::update', 'targets' => targets, 'mode' => mode, 'release_manifest' => {}).ok?).to be(false)
      end
    end

    let(:inputs) { { 'update-good' => { 'transaction' => 'good' }, 'update-failed' => { 'transaction' => 'failed' } } }
    let(:commands) { { 'update-good' => ['nest', 'reset', '--transaction', 'good'], 'update-failed' => ['nest', 'reset', '--transaction', 'failed'] } }
    let(:bound) { { 'release' => "sha256:#{'a' * 64}", 'policy_sha256' => 'b' * 64, 'inputs' => inputs, 'commands' => commands, 'waves' => [['update-good'], ['update-failed']] } }
    let(:manifest) { { 'kind' => 'fixture-manifest' } }
    let(:params) { { 'targets' => targets, 'mode' => 'prepare', 'policy' => {}, 'preparation' => inputs, 'output_dir' => '/fixture', 'release_manifest' => manifest } }
    let(:scope_receipt) do
      { 'kind' => 'nest_update_scope_index', 'mode' => params['mode'], 'policy_sha256' => bound['policy_sha256'],
        'readback_verified' => true, 'reboot_eligible' => [], 'execution_authorized' => false, 'acceptance_recorded' => false }
    end

    context 'control-plane maintenance admission' do
      let(:targets) { ['control3'] }
      let(:inputs) { { 'control3' => { 'transaction' => 'fixture' } } }
      let(:commands) { { 'control3' => ['nest', 'reset', '--transaction', 'fixture'] } }
      let(:bound) { { 'release' => "sha256:#{'a' * 64}", 'policy_sha256' => 'b' * 64, 'inputs' => inputs, 'commands' => commands, 'waves' => [['control3']] } }
      let(:maintenance) do
        { 'survivor' => 'control1', 'client' => 'owl', 'advertisers' => {}, 'physical_domains' => {}, 'ceph_fsid' => '12345678-1234-1234-1234-123456789abc' }
      end

      it 'rejects missing admission without touching a host or creating a report' do
        allow_any_command.not_be_called
        expect_task('nest::retain_update_report').not_be_called
        expect_plan('nest::kubernetes::check_control_plane_maintenance').not_be_called
        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'cannot use the API-only null Ceph option to prepare a controller root' do
        allow_any_command.not_be_called
        expect_plan('nest::kubernetes::check_control_plane_maintenance').not_be_called
        maintenance['ceph_fsid'] = nil
        expect(run_plan('nest::host::update', params.merge('maintenance' => { 'control3' => maintenance })).ok?).to be(false)
      end

      it 'checks all controller admission inputs before preparation and rechecks immediately before its exact native command' do
        admitted = 0
        expect_plan('nest::kubernetes::check_control_plane_maintenance').with_params(maintenance.merge('target' => 'control3')).be_called_times(2).return do |**_options|
          admitted += 1
          Bolt::PlanResult.new({ 'kind' => 'nest_control_plane_maintenance_check' }, 'success')
        end
        expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => 'fixture', 'release' => bound['release'], 'hostname' => 'control3', 'output_dir' => '/fixture')
        expect_command('nest reset --transaction fixture').return do |targets:, command:, **_options|
          expect(admitted).to eq(2)
          Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => 'fixture report', 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
        end
        retain = { 'report' => 'fixture report', 'transaction' => 'fixture', 'release' => bound['release'], 'hostname' => 'control3', 'output_dir' => '/fixture' }
        expect_task('nest::retain_update_report').with_params(retain).always_return('state' => 'prepared')
        result = run_plan('nest::host::update', params.merge('maintenance' => { 'control3' => maintenance }))
        expect(result.ok?).to be(true)
        expect(result.value['reboot_eligible']).to eq([])
      end

      it 'does not reset after the second admission check fails' do
        calls = 0
        expect_plan('nest::kubernetes::check_control_plane_maintenance').be_called_times(2).return do |**_options|
          calls += 1
          (calls == 1) ? Bolt::PlanResult.new({}, 'success') : Bolt::PlanResult.new(Bolt::Error.new('Lost survivor', 'nest/maintenance'), 'failure')
        end
        expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => 'fixture', 'release' => bound['release'], 'hostname' => 'control3', 'output_dir' => '/fixture')
        allow_any_command.not_be_called
        expect(run_plan('nest::host::update', params.merge('maintenance' => { 'control3' => maintenance })).ok?).to be(false)
      end

      it 'rejects a controller sharing a preparation wave regardless of the declared scheduling domains' do
        bound['waves'] = [['control3', 'other']]
        allow_any_command.not_be_called
        expect_plan('nest::kubernetes::check_control_plane_maintenance').not_be_called
        expect(run_plan('nest::host::update', params.merge('maintenance' => { 'control3' => maintenance })).ok?).to be(false)
      end
    end

    before :each do
      allow_task('nest::retain_update_scope').with_targets('localhost').always_return(scope_receipt)
      allow_task('nest::update_prepare_inputs').with_targets('localhost').always_return(bound)
      allow_task('nest::update_generation_binding').with_targets('localhost').always_return('reset_authorized' => false)
      bound['backup_requirements'] = targets.each_with_object({}) { |name, entries| entries[name] = [] }
      bound['inputs_sha256'] = 'c' * 64
      inputs.each do |name, entry|
        entry['generation_policy'] = { 'hostname' => name, 'release' => bound['release'], 'destination' => '/fixture/root' }
      end
      inputs.each_key do |name|
        ['preflight', 'initiation'].each do |stage|
          allow_plan('nest::host::stage_generation').with_params(generation_params(name, stage)).always_return('retained' => generation_receipt(name, stage))
        end
      end
      inputs.each_key do |name|
        allow_plan('nest::host::check_update_capacity').with_params(capacity_params(name)).always_return(capacity_receipt(name))
      end
      expect_plan('nest::host::reboot').not_be_called
      expect_plan('nest::puppet::run').not_be_called
    end

    def generation_binding(name, stage)
      { 'transaction' => inputs[name]['transaction'], 'policy_sha256' => bound['policy_sha256'], 'stage' => stage }
    end

    def generation_params(name, stage = 'preflight')
      { 'targets' => name, 'policy' => inputs[name]['generation_policy'], 'manifest' => manifest, 'verify_only' => true,
        'output_dir' => '/fixture', 'binding' => generation_binding(name, stage) }
    end

    def generation_receipt(name, stage = 'preflight')
      { 'kind' => 'nest_generation_retention_receipt', 'readback_verified' => true, 'sealed' => true,
        'hostname' => name, 'release' => bound['release'], 'reset_authorized' => false, 'preparation' => generation_binding(name, stage) }
    end

    def capacity_params(name)
      { 'target' => name, 'release' => bound['release'], 'inputs' => inputs[name], 'output_dir' => '/fixture', 'binding' => generation_binding(name, 'preflight') }
    end

    def capacity_receipt(name)
      { 'capacity_admitted' => true, 'readback_verified' => true, 'reset_authorized' => false, 'preparation' => generation_binding(name, 'preflight') }
    end

    context 'sealed local generation prerequisites' do
      it 'preflights every selected native capacity before the first reset and retains the receipts' do
        checked = []
        inputs.each_key do |name|
          expect_plan('nest::host::check_update_capacity').with_params(capacity_params(name)).return do |**_options|
            checked << name
            Bolt::PlanResult.new(capacity_receipt(name), 'success')
          end
        end
        commands.each_value do |argv|
          expect_command(argv.join(' ')).return do |targets:, command:, **_options|
            expect(checked).to eq(inputs.keys)
            Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => 'report', 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
          end
        end
        result = run_plan('nest::host::update', params)
        expect(result.ok?).to be(true)
        expect(result.value['capacity_preflight'].length).to eq(2)
      end

      it 'does not start even the canary when a later selected host has unknown capacity' do
        expect_plan('nest::host::check_update_capacity').with_params(capacity_params('update-failed')).error_with('kind' => 'fixture/capacity', 'msg' => 'Unknown finite limit')
        allow_any_command.not_be_called
        expect_plan('nest::host::check_update_backup').not_be_called
        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'refuses an admitted capacity result without supervisor readback' do
        expect_plan('nest::host::check_update_capacity').always_return('capacity_admitted' => true, 'readback_verified' => false)
        allow_any_command.not_be_called
        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'requires the complete manifest before any host action' do
        allow_any_command.not_be_called
        expect_task('nest::update_prepare_inputs').not_be_called
        expect(run_plan('nest::host::update', params.reject { |key, _value| key == 'release_manifest' }).ok?).to be(false)
      end

      ['missing', 'transaction', 'policy_sha256', 'stage', 'reset_authorized'].each do |changed|
        it "refuses unrelated retained capacity context: #{changed}" do
          receipt = capacity_receipt('update-failed')
          if changed == 'missing'
            receipt.delete('preparation')
          elsif changed == 'reset_authorized'
            receipt['reset_authorized'] = true
          else
            receipt['preparation'][changed] = { 'transaction' => 'other', 'policy_sha256' => 'e' * 64, 'stage' => 'initiation' }[changed]
          end
          expect_plan('nest::host::check_update_capacity').with_params(capacity_params('update-failed')).always_return(receipt)
          allow_any_command.not_be_called
          expect_plan('nest::host::check_update_backup').not_be_called
          expect(run_plan('nest::host::update', params).ok?).to be(false)
        end
      end

      it 'binds every generation and exact wave scope before contacting any host' do
        policies = inputs.transform_values { |entry| entry['generation_policy'] }
        binding = { 'manifest' => manifest, 'policies' => policies, 'scope' => params['policy'] }
        expect_task('nest::update_generation_binding').with_params(binding).error_with('kind' => 'fixture/binding', 'msg' => 'Wrong release')
        expect_plan('nest::host::stage_generation').not_be_called
        expect_task('nest::retain_update_report').not_be_called
        allow_any_command.not_be_called
        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      before :each do
        allow_task('nest::retain_update_report').always_return('state' => 'prepared')
      end

      it 'checks every exact seal before reset and repeats each affected check at initiation' do
        checked = Hash.new(0)
        inputs.each_key do |name|
          ['preflight', 'initiation'].each do |stage|
            expect_plan('nest::host::stage_generation').with_params(generation_params(name, stage)).return do |**_options|
              checked[name] += 1
              Bolt::PlanResult.new({ 'retained' => generation_receipt(name, stage) }, 'success')
            end
          end
        end
        commands.each do |name, argv|
          expect_command(argv.join(' ')).return do |targets:, command:, **_options|
            expect(checked.values).to all(be >= 1)
            expect(checked[name]).to eq(2)
            values = { 'stdout' => 'report', 'stderr' => '', 'exit_code' => 0 }
            Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, values, 'command', command, []) })
          end
        end

        result = run_plan('nest::host::update', params)
        expect(result.ok?).to be(true)
        expect(result.value['generation_preflight']).to eq(inputs.keys.map { |name| generation_receipt(name) })
        expect(result.value['waves'][0][0]['generation_verification']).to eq(generation_receipt('update-good', 'initiation'))
      end

      it 'refuses the canary when a later selected generation fails preflight' do
        verify = generation_params('update-failed')
        expect_plan('nest::host::stage_generation').with_params(verify).error_with('kind' => 'fixture/seal', 'msg' => 'Corrupt generation')
        allow_any_command.not_be_called

        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'refuses reset when a seal changes between preflight and initiation' do
        verify = generation_params('update-good', 'initiation')
        expect_plan('nest::host::stage_generation').with_params(verify).error_with('kind' => 'fixture/seal', 'msg' => 'Changed seal')
        allow_any_command.not_be_called

        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      ['preflight', 'initiation'].each do |stage|
        it "refuses the other preparation stage even with matching transaction and wave policy at #{stage}" do
          name = (stage == 'preflight') ? 'update-failed' : 'update-good'
          opposite = (stage == 'preflight') ? 'initiation' : 'preflight'
          receipt = generation_receipt(name, opposite)
          expect_plan('nest::host::stage_generation').with_params(generation_params(name, stage)).always_return('retained' => receipt)
          allow_any_command.not_be_called

          expect(run_plan('nest::host::update', params).ok?).to be(false)
        end

        [
          { 'readback_verified' => false },
          { 'hostname' => 'other' },
          { 'release' => "sha256:#{'d' * 64}" },
          { 'sealed' => false },
          { 'reset_authorized' => true },
          { 'kind' => 'nest_generation_transfer_report' },
          { 'preparation' => nil },
          { 'preparation' => { 'transaction' => 'other', 'policy_sha256' => 'b' * 64, 'stage' => 'preflight' } },
          { 'preparation' => { 'transaction' => 'good', 'policy_sha256' => 'c' * 64, 'stage' => 'initiation' } },
        ].each do |change|
          it "refuses reset when #{stage} generation retention is inconsistent: #{change}" do
            name = (stage == 'preflight') ? 'update-failed' : 'update-good'
            receipt = generation_receipt(name, stage).merge(change)
            expect_plan('nest::host::stage_generation').with_params(generation_params(name, stage)).always_return('retained' => receipt)
            allow_any_command.not_be_called

            result = run_plan('nest::host::update', params)
            expect(result.ok?).to be(false)
            # Bolt's mock parallel executor wraps initiation failures; the
            # no-command and exact check-count assertions protect that boundary.
            expect(result.value.kind).to eq('nest/update-generation-retention') if stage == 'preflight'
          end
        end
      end

      it 'refuses an old generation subplan result lacking supervisor retention' do
        expect_plan('nest::host::stage_generation').always_return('sealed' => true)
        allow_any_command.not_be_called
        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'rechecks exact preparation input identity even when native argv is unchanged' do
        calls = 0
        expect_task('nest::update_prepare_inputs').be_called_times(2).return do |targets:, **_options|
          calls += 1
          value = (calls == 1) ? bound : bound.merge('inputs_sha256' => 'd' * 64)
          Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_task(target, JSON.generate(value), '', 0, 'nest::update_prepare_inputs', []) })
        end
        allow_any_command.not_be_called

        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end
    end

    context 'existing backup prerequisites' do
      let(:backup_check) do
        { 'kind' => 'hermes', 'target' => 'fixture-backup', 'user' => 'joy', 'backup_dir' => '/fixture/backups',
          'checkpoint' => 'fixture', 'expected_sha256' => 'c' * 64, 'max_age_seconds' => 3600, 'required_profiles' => ['talon'], 'hold_id' => 'release-fixture' }
      end
      let(:backup_receipt) { { 'verification_retained' => true, 'hold_checked' => true, 'readback_verified' => true, 'retention_lease' => false } }

      def verify_params(stage, host = 'update-good')
        {
          'check' => backup_check,
          'retention' => { 'transaction' => inputs[host]['transaction'], 'release' => bound['release'],
                                        'hostname' => host, 'policy_sha256' => bound['policy_sha256'], 'stage' => stage, 'output_dir' => '/fixture' },
        }
      end

      before :each do
        bound['backup_requirements']['update-good'] = [backup_check]
        allow_task('nest::retain_update_report').always_return('state' => 'prepared')
      end

      it 'checks the full backup scope before any reset and repeats the affected prerequisite before initiation' do
        checks = 0
        ['preflight', 'initiation'].each do |stage|
          expect_plan('nest::host::check_update_backup').with_params(verify_params(stage)).return do |**_options|
            checks += 1
            Bolt::PlanResult.new(backup_receipt, 'success')
          end
        end
        commands.each_value do |argv|
          expect_command(argv.join(' ')).return do |targets:, command:, **_options|
            expect(checks).to eq(2)
            Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => 'report', 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
          end
        end

        result = run_plan('nest::host::update', params)
        expect(result.ok?).to be(true)
        expect(result.value['backup_preflight']).to eq([[backup_receipt], []])
        expect(result.value['waves'][0][0]['backup_verification']).to eq([backup_receipt])
      end

      it 'does not start even the canary when a later host backup preflight fails' do
        bound['backup_requirements']['update-good'] = []
        bound['backup_requirements']['update-failed'] = [backup_check]
        expect_plan('nest::host::check_update_backup').with_params(verify_params('preflight', 'update-failed')).error_with('kind' => 'fixture/backup', 'msg' => 'Stale generation')
        allow_any_command.not_be_called

        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'does not reset after a previously valid backup becomes unavailable at initiation' do
        expect_plan('nest::host::check_update_backup').with_params(verify_params('preflight')).always_return(backup_receipt)
        expect_plan('nest::host::check_update_backup').with_params(verify_params('initiation')).error_with('kind' => 'fixture/backup', 'msg' => 'Busy backup')
        allow_any_command.not_be_called

        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      it 'rechecks the preparation window after backup readback rather than treating it as a lease' do
        checks = 0
        ['preflight', 'initiation'].each do |stage|
          expect_plan('nest::host::check_update_backup').with_params(verify_params(stage)).return do |**_options|
            checks += 1
            Bolt::PlanResult.new(backup_receipt, 'success')
          end
        end
        expect_task('nest::update_prepare_inputs').be_called_times(2).return do |targets:, **_options|
          value = (checks == 2) ? { '_error' => { 'kind' => 'nest/update-prepare-inputs', 'msg' => 'Expired window' } } : bound
          status = (checks == 2) ? 1 : 0
          Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_task(target, JSON.generate(value), '', status, 'nest::update_prepare_inputs', []) })
        end
        allow_any_command.not_be_called

        expect(run_plan('nest::host::update', params).ok?).to be(false)
      end

      ['preflight', 'initiation'].each do |stage|
        it "refuses reset when #{stage} verification has no retained readback" do
          if stage == 'initiation'
            expect_plan('nest::host::check_update_backup').with_params(verify_params('preflight')).always_return(backup_receipt)
          end
          expect_plan('nest::host::check_update_backup').with_params(verify_params(stage)).always_return('verification_retained' => true, 'readback_verified' => false)
          allow_any_command.not_be_called

          expect(run_plan('nest::host::update', params).ok?).to be(false)
        end
      end
    end

    it 'rechecks admission after destination preflight and stops before the next host when its window expires' do
      admissions = 0
      expect_task('nest::update_prepare_inputs').with_targets('localhost').be_called_times(3).return do |targets:, **_options|
        admissions += 1
        if admissions < 3
          value = bound
          status = 0
        else
          value = { '_error' => { 'kind' => 'nest/update-prepare-inputs', 'msg' => 'Expired window' } }
          status = 1
        end
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_task(target, JSON.generate(value), '', status, 'nest::update_prepare_inputs', []) })
      end
      ['good', 'failed'].each do |id|
        host = (id == 'good') ? 'update-good' : 'update-failed'
        expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => id, 'release' => bound['release'], 'hostname' => host, 'output_dir' => '/fixture')
      end
      expect_command('nest reset --transaction good').return do |targets:, command:, **_options|
        expect(admissions).to eq(2)
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => 'good report', 'stderr' => '', 'exit_code' => 0 }, 'command', command, []) })
      end
      retain = { 'report' => 'good report', 'transaction' => 'good', 'release' => bound['release'], 'hostname' => 'update-good', 'output_dir' => '/fixture' }
      expect_task('nest::retain_update_report').with_params(retain).always_return('state' => 'prepared')
      expect_command('nest reset --transaction failed').not_be_called

      result = run_plan('nest::host::update', params)

      expect(result.ok?).to be(false)
      expect(admissions).to eq(3)
    end

    it 'preflights every destination and retains each successful native transaction without reboot eligibility' do
      ['good', 'failed'].each do |id|
        host = (id == 'good') ? 'update-good' : 'update-failed'
        check_params = { 'action' => 'check', 'transaction' => id, 'release' => bound['release'], 'hostname' => host, 'output_dir' => '/fixture' }
        expect_task('nest::retain_update_report').with_params(check_params).always_return('destination_checked' => true)
      end
      expect_command('nest reset --transaction good').with_targets('update-good').always_return('stdout' => 'good report')
      expect_command('nest reset --transaction failed').with_targets('update-failed').always_return('stdout' => 'failed report')
      ['good', 'failed'].each do |id|
        host = (id == 'good') ? 'update-good' : 'update-failed'
        retain_params = { 'report' => "#{id} report", 'transaction' => id, 'release' => bound['release'], 'hostname' => host, 'output_dir' => '/fixture' }
        expect_task('nest::retain_update_report').with_params(retain_params).always_return('state' => 'prepared', 'readback_verified' => true)
      end

      result = run_plan('nest::host::update', params)

      expect(result.ok?).to be(true)
      expect(result.value['reboot_eligible']).to eq([])
      expect(result.value['waves'].length).to eq(2)
    end

    it 'retains a stopped native outcome and never starts the next wave or retries' do
      expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => 'good', 'release' => bound['release'], 'hostname' => 'update-good', 'output_dir' => '/fixture')
      expect_task('nest::retain_update_report').with_params('action' => 'check', 'transaction' => 'failed', 'release' => bound['release'], 'hostname' => 'update-failed', 'output_dir' => '/fixture')
      expect_command('nest reset --transaction good').with_targets('update-good').return do |targets:, command:, **_options|
        Bolt::ResultSet.new(targets.map { |target| Bolt::Result.for_command(target, { 'stdout' => 'stopped report', 'stderr' => '', 'exit_code' => 2 }, 'command', command, []) })
      end
      retain_params = { 'report' => 'stopped report', 'transaction' => 'good', 'release' => bound['release'], 'hostname' => 'update-good', 'output_dir' => '/fixture' }
      expect_task('nest::retain_update_report').with_params(retain_params).always_return('state' => 'stopped')
      expect_command('nest reset --transaction failed').not_be_called

      expect(run_plan('nest::host::update', params).ok?).to be(false)
    end

    it 'refuses a bad destination before any native reset' do
      expect_task('nest::retain_update_report').error_with('kind' => 'nest/update-report', 'msg' => 'Invalid destination')
      commands.each_value { |argv| expect_command(argv.join(' ')).not_be_called }

      expect(run_plan('nest::host::update', params).ok?).to be(false)
    end
  end
end
