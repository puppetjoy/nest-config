#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'tmpdir'
require_relative 'update_catalog_report'

# Each native invocation owns a fresh private report path. A later agent run
# cannot replace its evidence, even after the managed per-apply lock is released.
module NestUpdateCatalogApply
  REPORT = NestUpdateCatalogReport
  KEYS = ['hostname', 'certname', 'boot_id', 'configuration_version'].freeze
  ARGS = ['--environment', 'main', '--no-noop', '--no-use_cached_catalog',
          '--no-usecacheonfailure', '--tags=', '--skip_tags='].freeze

  def self.expectations(value)
    REPORT.require_value(value.is_a?(Hash) && (value.keys - ['code_id']).sort == KEYS.sort)
    REPORT.expectations(value.merge('transaction_uuid' => value['boot_id'], 'status' => 'unchanged', 'not_before' => 1, 'not_after' => 1))
    value
  end

  def self.identity(expected, certname, hostname, boot)
    REPORT.require_value(certname == expected['certname'] && hostname == expected['hostname'] && boot.call == expected['boot_id'])
  end

  def self.execute(wrapper, path, log)
    env = { 'PUPPET_PRESERVE_DETAILED_EXIT' => 'true', 'PUPPET_EXTRA_ARGS' => '',
            'FACTER_build' => nil, 'FACTER_skip_module_rebuild' => nil }
    args = ARGS + ['--lastrunreport', path, '--lastrunfile', "#{path}.summary"]
    pid = Process.spawn(env, '/bin/sh', wrapper, *args, out: log, err: log)
    _pid, status = Process.wait2(pid)
    status.exitstatus
  end

  def self.apply(expected, dir, name, wrapper, runner, reader, clock)
    path = File.join(dir, "#{name}.yaml")
    REPORT.require_value(!File.exist?(path))
    before = clock.call.floor
    native_exit = runner.call(wrapper, path, File.join(dir, "#{name}.log"))
    after = clock.call.ceil
    result = { 'native_exit' => native_exit, 'report_bound' => false }
    return result unless [0, 2].include?(native_exit)

    # This file did not exist before this invocation. Its UUID is observed, not
    # supplied by a caller or borrowed from the shared last-run report.
    raw = reader.call(path)
    uuid = REPORT.scalars(raw)['transaction_uuid']
    REPORT.require_value(REPORT::UUID.match?(uuid))
    bound = REPORT.bind(raw, expected.merge('transaction_uuid' => uuid, 'status' => native_exit.zero? ? 'unchanged' : 'changed',
                                           'not_before' => before, 'not_after' => after))
    REPORT.require_value(reader.call(path) == raw)
    result.merge('report_bound' => true, 'report' => bound)
  rescue REPORT::Unavailable, Psych::Exception, ArgumentError, TypeError, SystemCallError
    # Preserve a known native exit even when its report cannot be accepted.
    { 'native_exit' => native_exit, 'report_bound' => false }
  end

  def self.run(expected, state_dir:, certname:, hostname: Socket.gethostname, boot: REPORT.method(:boot_id),
               wrapper: File.expand_path('../scripts/run_puppet.sh', __dir__), runner: method(:execute),
               reader: REPORT.method(:read_report), clock: -> { Time.now.to_f })
    expectations(expected)
    identity(expected, certname, hostname, boot)
    result = { 'schema' => 1, 'kind' => 'nest_update_catalog_bound', 'result' => 'fail',
               'hostname' => hostname, 'boot_id' => expected['boot_id'], 'configuration_version' => expected['configuration_version'],
               'repeat_attempted' => false, 'converged' => false, 'served_source_verified' => false,
               'acceptance_recorded' => false }
    Dir.mktmpdir('nest-catalog-', state_dir) do |dir|
      first = apply(expected, dir, 'main', wrapper, runner, reader, clock)
      result['main'] = first
      identity(expected, certname, hostname, boot)
      return result unless first['report_bound']

      result['repeat_attempted'] = true
      second = apply(expected, dir, 'repeat', wrapper, runner, reader, clock)
      result['repeat'] = second
      identity(expected, certname, hostname, boot)
      REPORT.require_value(!second['report_bound'] || first['report']['transaction_uuid'] != second['report']['transaction_uuid'])
      result['converged'] = second['report_bound'] && second['native_exit'].zero?
      result['result'] = 'pass' if result['converged']
    end
    result
  rescue REPORT::Unavailable
    raise unless result

    result.merge('result' => 'fail', 'converged' => false, 'identity_binding_failed' => true)
  end

  def self.main
    raw = $stdin.read(16_385)
    REPORT.require_value(raw.bytesize <= 16_384 && Process.euid.zero? && RUBY_PLATFORM.include?('linux'))
    params = JSON.parse(raw)
    REPORT.require_value(params.is_a?(Hash) && params.key?('expectations') && params['_noop'] != true &&
                         params.keys.all? { |key| key == 'expectations' || key.start_with?('_') })
    expectations(params['expectations'])
    require 'puppet'
    Puppet.initialize_settings(['--run_mode', 'agent'])
    Puppet.settings.use(:main, :agent)
    state = File.lstat(Puppet[:statedir])
    REPORT.require_value(state.directory? && state.uid.zero? && state.mode.nobits?(0o022))
    puts JSON.generate(run(params['expectations'], state_dir: Puppet[:statedir], certname: Puppet[:certname]))
    0
  rescue REPORT::Unavailable, JSON::ParserError, Psych::Exception, ArgumentError, TypeError, SystemCallError, SystemStackError
    puts JSON.generate('_error' => { 'kind' => 'nest/update-catalog-apply-unavailable',
                                    'msg' => 'Catalog invocation or binding failed; inspect before rerunning; no acceptance recorded' })
    1
  end
end

exit NestUpdateCatalogApply.main if __FILE__ == $PROGRAM_NAME
