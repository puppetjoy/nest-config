#!/usr/bin/env ruby
# frozen_string_literal: true

require_relative 'update_catalog_report'
require 'open3'

# Observe the native JSON cache without loading a catalog, syncing plugins,
# contacting a server, instantiating YAML objects or changing agent state.
module NestCompilerCatalogCache
  REPORT = NestUpdateCatalogReport
  LEGACY_VERSION = %r{\A[0-9a-f]{7,40}\z}
  DARWIN_UUID = %r{\A[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\z}
  WINDOWS_BOOT = 'NtQuerySystemInformation.SystemBootEnvironmentInformation.BootIdentifier'

  def self.platform
    return 'linux' if RUBY_PLATFORM.include?('linux')
    return 'darwin' if RUBY_PLATFORM.include?('darwin')
    return 'windows' if RUBY_PLATFORM == 'x64-mingw32'
    raise REPORT::Unavailable, 'Unsupported native cache platform'
  end

  def self.boot_id(native_platform = platform)
    return REPORT.boot_id if native_platform == 'linux'
    return NestCompilerWindowsCache.boot_id if native_platform == 'windows'
    REPORT.require_value(native_platform == 'darwin')
    output, _error, status = Open3.capture3('/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid')
    # Preserve the native uppercase token exactly. Only sysctl's single output
    # record terminator is removed; malformed or differently cased IDs refuse.
    REPORT.require_value(status.success? && output.end_with?("\n"))
    value = output.delete_suffix("\n")
    REPORT.require_value(DARWIN_UUID.match?(value))
    value
  end

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

  def self.fingerprint(stat)
    [stat.dev, stat.ino, stat.size, stat.mtime, stat.ctime, stat.uid, stat.gid, stat.mode, stat.nlink]
  end

  def self.read_cache(path)
    # Native JSON caches are root:root 0660. Permit that native mode without
    # weakening the independent last-run report reader's stricter contract.
    REPORT.require_value(File.absolute_path(path) == path)
    before = File.lstat(path)
    REPORT.require_value(before.file? && owned?(before) && before.size <= REPORT::LIMIT)
    File.open(path, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |file|
      stat = file.stat
      REPORT.require_value(stat.file? && owned?(stat) && stat.size <= REPORT::LIMIT && fingerprint(before) == fingerprint(stat))
      raw = file.read(REPORT::LIMIT + 1)
      REPORT.require_value(raw.bytesize <= REPORT::LIMIT && fingerprint(file.stat) == fingerprint(stat) && fingerprint(File.lstat(path)) == fingerprint(stat))
      raw
    end
  end

  def self.collect(expected, path:, certname:, server:, hostname: Socket.gethostname, boot: REPORT.method(:boot_id),
                   reader: method(:read_cache), clock: -> { Time.now.to_i }, native_platform: 'linux')
    expectations(expected)
    REPORT.require_value(['linux', 'darwin', 'windows'].include?(native_platform))
    pattern = (native_platform == 'darwin') ? DARWIN_UUID : REPORT::UUID
    before = boot.call
    REPORT.require_value(before.is_a?(String) && pattern.match?(before) && expected == { 'hostname' => hostname, 'certname' => certname, 'server' => server })
    raw = reader.call(path)
    cache = headers(raw, certname)
    REPORT.require_value(reader.call(path) == raw && boot.call == before)
    result = { 'schema' => 1, 'kind' => 'nest_compiler_catalog_cache', 'hostname' => hostname, 'certname' => certname, 'server' => server,
      'boot_id' => before, 'observed_at' => clock.call, 'environment' => 'main', 'cache' => cache,
      'read_only' => true, 'catalog_applied' => false, 'acceptance_recorded' => false }
    result.merge!('schema' => 2, 'platform' => 'darwin', 'boot_source' => 'kern.bootsessionuuid') if native_platform == 'darwin'
    result.merge!('schema' => 3, 'platform' => 'windows', 'boot_source' => WINDOWS_BOOT) if native_platform == 'windows'
    result
  end

  def self.main
    Timeout.timeout(30) do
      raw = $stdin.read(16_385)
      REPORT.require_value(raw.bytesize <= 16_384)
      native_platform = platform
      if native_platform == 'windows'
        require_relative 'compiler_windows_cache'
        REPORT.require_value(NestCompilerWindowsCache.elevated?)
      else
        REPORT.require_value(Process.euid.zero?)
      end
      params = JSON.parse(raw, object_class: UniqueHash)
      REPORT.require_value(params.is_a?(Hash) && params.key?('expectations') && params.keys.all? { |key| key == 'expectations' || key.start_with?('_') })
      expectations(params['expectations'])
      require 'puppet'
      Puppet.initialize_settings(['--run_mode', 'agent'])
      Puppet.settings.use(:main, :agent)
      certname = Puppet[:certname]
      REPORT.require_value(certname.is_a?(String) && REPORT::NAME.match?(certname))
      path = File.join(Puppet[:client_datadir], 'catalog', certname + '.json')
      reader = (native_platform == 'windows') ? NestCompilerWindowsCache.method(:read_cache) : method(:read_cache)
      puts JSON.generate(collect(params['expectations'], path: path, certname: certname, server: Puppet[:server],
                                 native_platform: native_platform, boot: -> { boot_id(native_platform) }, reader: reader))
    end
    0
  rescue REPORT::Unavailable, JSON::ParserError, ArgumentError, TypeError, SystemCallError, Timeout::Error, SystemStackError, LoadError
    puts JSON.generate('_error' => { 'kind' => 'nest/compiler-catalog-cache-unavailable',
                                    'msg' => 'Catalog cache observation unavailable; no deployment or acceptance authorized' })
    1
  end
end

exit NestCompilerCatalogCache.main if __FILE__ == $PROGRAM_NAME
