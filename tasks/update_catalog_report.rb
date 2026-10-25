#!/usr/bin/env ruby
# frozen_string_literal: true

require 'digest'
require 'json'
require 'psych'
require 'socket'
require 'time'
require 'timeout'

# Read selected native report scalars without instantiating YAML objects or logs.
module NestUpdateCatalogReport
  LIMIT = 32 * 1024 * 1024
  UUID = %r{\A[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\z}
  SHA = %r{\A[0-9a-f]{40}\z}
  CODE_ID = %r{\Asha256:[0-9a-f]{64}\z}
  NAME = %r{\A[A-Za-z0-9][A-Za-z0-9_.-]{0,252}\z}
  FIELDS = ['host', 'environment', 'configuration_version', 'transaction_uuid', 'catalog_uuid',
            'time', 'status', 'noop', 'cached_catalog_status', 'transaction_completed'].freeze

  class Unavailable < StandardError; end

  def self.require_value(condition)
    raise Unavailable, 'Catalog report binding unavailable' unless condition
  end

  def self.expectations(value)
    names = ['hostname', 'certname', 'boot_id', 'configuration_version', 'transaction_uuid', 'status', 'not_before', 'not_after']
    require_value(value.is_a?(Hash) && (value.keys - ['code_id']).sort == names.sort)
    require_value(!value.key?('code_id') || (value['code_id'].is_a?(String) && CODE_ID.match?(value['code_id'])))
    ['hostname', 'certname'].each { |key| require_value(value[key].is_a?(String) && NAME.match?(value[key])) }
    ['boot_id', 'transaction_uuid'].each { |key| require_value(value[key].is_a?(String) && UUID.match?(value[key])) }
    require_value(value['configuration_version'].is_a?(String) && SHA.match?(value['configuration_version']))
    require_value(['changed', 'unchanged'].include?(value['status']))
    require_value(['not_before', 'not_after'].all? { |key| value[key].is_a?(Integer) && value[key].positive? })
    require_value(value['not_before'] <= value['not_after'] && value['not_after'] - value['not_before'] <= 86_400)
    value
  end

  def self.scalars(raw, code_id: false)
    require_value(raw.bytesize <= LIMIT)
    fields = code_id ? FIELDS + ['code_id'] : FIELDS
    stream = Psych.parse_stream(raw)
    require_value(stream.children.length == 1)
    root = stream.children.first.root
    require_value(root.is_a?(Psych::Nodes::Mapping) && root.tag == '!ruby/object:Puppet::Transaction::Report')
    result = {}
    keys = []
    root.children.each_slice(2) do |key, node|
      require_value(key.is_a?(Psych::Nodes::Scalar) && !keys.include?(key.value))
      keys << key.value
      next unless fields.include?(key.value)
      require_value(node.is_a?(Psych::Nodes::Scalar) && node.anchor.nil?)
      require_value([nil, 'tag:yaml.org,2002:str'].include?(node.tag)) if key.value == 'code_id'
      if ['noop', 'transaction_completed'].include?(key.value)
        require_value(node.plain && ['true', 'false'].include?(node.value) && [nil, 'tag:yaml.org,2002:bool'].include?(node.tag))
        result[key.value] = node.value == 'true'
      else
        require_value(node.value.bytesize <= 256)
        result[key.value] = node.value
      end
    end
    require_value(result.keys.sort == fields.sort)
    result
  end

  def self.bind(raw, expected)
    expected = expectations(expected)
    report = scalars(raw, code_id: expected.key?('code_id'))
    require_value(!expected.key?('code_id') || report['code_id'] == expected['code_id'])
    require_value(report['host'] == expected['certname'] && report['environment'] == 'main')
    require_value(report['configuration_version'] == expected['configuration_version'])
    require_value(report['transaction_uuid'] == expected['transaction_uuid'] && UUID.match?(report['catalog_uuid']))
    require_value(report['status'] == expected['status'] && report['noop'] == false && report['transaction_completed'] == true)
    require_value(report['cached_catalog_status'] == 'not_used')
    require_value(%r{\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\z}.match?(report['time']))
    stamp = Time.iso8601(report['time'])
    require_value(stamp >= Time.at(expected['not_before']) && stamp <= Time.at(expected['not_after']))
    report.merge('report_sha256' => Digest::SHA256.hexdigest(raw))
  end

  def self.read_report(path)
    File.open(path, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |file|
      stat = file.stat
      require_value(stat.file? && stat.uid.zero? && stat.mode.nobits?(0o022) && stat.size <= LIMIT)
      raw = file.read(LIMIT + 1)
      after = file.stat
      require_value(raw.bytesize <= LIMIT && [after.dev, after.ino, after.size, after.mtime, after.ctime] == [stat.dev, stat.ino, stat.size, stat.mtime, stat.ctime])
      raw
    end
  end

  def self.boot_id
    value = File.read('/proc/sys/kernel/random/boot_id').strip
    require_value(UUID.match?(value))
    value
  end

  def self.collect(expected, path:, certname:, hostname: Socket.gethostname, boot: method(:boot_id), reader: method(:read_report))
    expectations(expected)
    before = boot.call
    require_value(hostname == expected['hostname'] && certname == expected['certname'] && before == expected['boot_id'])
    raw = reader.call(path)
    report = bind(raw, expected)
    require_value(reader.call(path) == raw && boot.call == before)
    { 'schema' => 1, 'kind' => 'nest_update_catalog_report', 'result' => 'pass', 'hostname' => hostname,
      'boot_id' => before, 'report' => report, 'acceptance_recorded' => false }
  end

  def self.main
    Timeout.timeout(30) do
      raw = $stdin.read(16_385)
      require_value(raw.bytesize <= 16_384 && Process.euid.zero?)
      params = JSON.parse(raw)
      require_value(params.is_a?(Hash) && params.key?('expectations') && params.keys.all? { |key| key == 'expectations' || key.start_with?('_') })
      expectations(params['expectations'])
      require 'puppet'
      # Agent application defaults and section match `puppet config print --section agent`.
      Puppet.initialize_settings(['--run_mode', 'agent'])
      Puppet.settings.use(:main, :agent)
      puts JSON.generate(collect(params['expectations'], path: Puppet[:lastrunreport], certname: Puppet[:certname]))
    end
    0
  rescue Unavailable, JSON::ParserError, Psych::Exception, ArgumentError, TypeError, SystemCallError, Timeout::Error, SystemStackError
    puts JSON.generate('_error' => { 'kind' => 'nest/update-catalog-report-unavailable', 'msg' => 'Catalog report binding unavailable; no acceptance recorded' })
    1
  end
end

exit NestUpdateCatalogReport.main if __FILE__ == $PROGRAM_NAME
