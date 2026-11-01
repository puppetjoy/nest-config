require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'
require 'shellwords'

RSpec.describe 'nest::puppet::run' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('puppet-run-spec-') }

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  it 'transports explicit maintenance exclusions as separate Puppet arguments' do
    invocations = []
    allow_any_script.return do |targets:, script:, **options|
      invocations << options
      Bolt::ResultSet.new(targets.map do |target|
        Bolt::Result.for_command(target, { 'stdout' => '', 'stderr' => '', 'exit_code' => 0 }, 'script', script, [])
      end)
    end
    result = run_plan('nest::puppet::run', 'targets' => 'owl', 'environment' => 'main',
                      'tags' => ['nest::app::hermes'], 'skip_tags' => ['systemd::user_service', 'restart_hermes_gateway_talon'])
    expect(result.ok?).to be(true)
    expect(invocations.length).to eq(1)
    expect(invocations.first).to include(:params)
    options = invocations.first.fetch(:params)
    expect(options.fetch(:run_as)).to eq('root')
    arguments = Shellwords.split(options.fetch(:env_vars).fetch('PUPPET_EXTRA_ARGS'))
    expect(arguments).to eq(['--environment', 'main', '--tags', 'nest::app::hermes',
                             '--skip_tags', 'systemd::user_service,restart_hermes_gateway_talon'])
  end

  it 'keeps ordinary Puppet runs unchanged when exclusions are omitted' do
    invocations = []
    allow_any_script.return do |targets:, script:, **options|
      invocations << options.fetch(:params)
      Bolt::ResultSet.new(targets.map do |target|
        Bolt::Result.for_command(target, { 'stdout' => '', 'stderr' => '', 'exit_code' => 0 }, 'script', script, [])
      end)
    end
    expect(run_plan('nest::puppet::run', 'targets' => 'owl').ok?).to be(true)
    expect(invocations.length).to eq(1)
    expect(Shellwords.split(invocations.first.fetch(:env_vars).fetch('PUPPET_EXTRA_ARGS'))).to eq([])
    expect(invocations.first.fetch(:run_as)).to eq('root')
  end
end
