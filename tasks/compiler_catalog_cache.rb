#!/usr/bin/env ruby
# frozen_string_literal: true

require_relative 'update_catalog_report'

# Observe the native JSON cache without loading a catalog, syncing plugins,
# contacting a server, instantiating YAML objects or changing agent state.
module NestCompilerCatalogCache
  REPORT = NestUpdateCatalogReport
  LEGACY_VERSION = %r{\A[0-9a-f]{7,40}\z}

  # Reject ambiguous JSON instead of silently keeping its last duplicate key.
  class UniqueHash < Hash
    def []=(key, value)
      REPORT.require_value(!key?(key))
      super
    end
  end

  def self.expectations(value)
    REPORT.require_value(value.is_a?(Hash) && value.keys.sort == ['certname', 'hostname', 'server'])
    value.each_value { |item| REPORT.require_value(item.is_a?(String) && REPORT::NAME.match?(item)) }
    value
  end

  def self.headers(raw, certname)
    REPORT.require_value(raw.bytesize <= REPORT::LIMIT)
    value = JSON.parse(raw, object_class: UniqueHash)
    REPORT.require_value(value.is_a?(Hash) && ['name', 'environment', 'version', 'code_id', 'catalog_uuid', 'resources'].all? { |key| value.key?(key) })
    REPORT.require_value(value['name'] == certname && value['environment'] == 'main')
    # Old mutable Nest compilers emitted git --short. Preserve that observation
    # exactly; it is not a full release source and must never bind an immutable ID.
    version_pattern = value['code_id'].nil? ? LEGACY_VERSION : REPORT::SHA
    REPORT.require_value(value['version'].is_a?(String) && version_pattern.match?(value['version']))
    REPORT.require_value(value['catalog_uuid'].is_a?(String) && REPORT::UUID.match?(value['catalog_uuid']))
    REPORT.require_value(value['code_id'].nil? || (value['code_id'].is_a?(String) && REPORT::CODE_ID.match?(value['code_id'])))
    REPORT.require_value(value['resources'].is_a?(Array) && !value['resources'].empty?)
    { 'configuration_version' => value['version'], 'code_id' => value['code_id'], 'catalog_uuid' => value['catalog_uuid'],
      'cache_sha256' => Digest::SHA256.hexdigest(raw) }
  end

  def self.owned?(stat)
    stat.uid.zero? && stat.mode.nobits?(0o002) && (stat.mode.nobits?(0o020) || stat.gid.zero?)
  end

  def self.read_cache(path)
    # Native JSON caches are root:root 0660. Permit that native mode without
    # weakening the independent last-run report reader's stricter contract.
    REPORT.require_value(File.absolute_path(path) == path)
    File.open(path, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |file|
      stat = file.stat
      REPORT.require_value(stat.file? && owned?(stat) && stat.size <= REPORT::LIMIT)
      raw = file.read(REPORT::LIMIT + 1)
      after = file.stat
      REPORT.require_value(raw.bytesize <= REPORT::LIMIT && [after.dev, after.ino, after.size, after.mtime, after.ctime] == [stat.dev, stat.ino, stat.size, stat.mtime, stat.ctime])
      raw
    end
  end

  def self.collect(expected, path:, certname:, server:, hostname: Socket.gethostname, boot: REPORT.method(:boot_id),
                   reader: method(:read_cache), clock: -> { Time.now.to_i })
    expectations(expected)
    before = boot.call
    REPORT.require_value(REPORT::UUID.match?(before) && expected == { 'hostname' => hostname, 'certname' => certname, 'server' => server })
    raw = reader.call(path)
    cache = headers(raw, certname)
    REPORT.require_value(reader.call(path) == raw && boot.call == before)
    { 'schema' => 1, 'kind' => 'nest_compiler_catalog_cache', 'hostname' => hostname, 'certname' => certname, 'server' => server,
      'boot_id' => before, 'observed_at' => clock.call, 'environment' => 'main', 'cache' => cache,
      'read_only' => true, 'catalog_applied' => false, 'acceptance_recorded' => false }
  end

  def self.main
    Timeout.timeout(30) do
      raw = $stdin.read(16_385)
      REPORT.require_value(raw.bytesize <= 16_384 && Process.euid.zero? && RUBY_PLATFORM.include?('linux'))
      params = JSON.parse(raw, object_class: UniqueHash)
      REPORT.require_value(params.is_a?(Hash) && params.key?('expectations') && params.keys.all? { |key| key == 'expectations' || key.start_with?('_') })
      expectations(params['expectations'])
      require 'puppet'
      Puppet.initialize_settings(['--run_mode', 'agent'])
      Puppet.settings.use(:main, :agent)
      certname = Puppet[:certname]
      REPORT.require_value(certname.is_a?(String) && REPORT::NAME.match?(certname))
      path = File.join(Puppet[:client_datadir], 'catalog', certname + '.json')
      puts JSON.generate(collect(params['expectations'], path: path, certname: certname, server: Puppet[:server]))
    end
    0
  rescue REPORT::Unavailable, JSON::ParserError, ArgumentError, TypeError, SystemCallError, Timeout::Error, SystemStackError
    puts JSON.generate('_error' => { 'kind' => 'nest/compiler-catalog-cache-unavailable',
                                    'msg' => 'Catalog cache observation unavailable; no deployment or acceptance authorized' })
    1
  end
end

exit NestCompilerCatalogCache.main if __FILE__ == $PROGRAM_NAME
