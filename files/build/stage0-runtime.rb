#!/usr/bin/env ruby

# Stage 0 must support Stage 1's Bolt interpreter, facts and native providers.
# No host configuration is changed; Augeas operates on a temporary fixture.
require 'timeout'

Timeout.timeout(90) do
  require 'puppet'
  require 'facter'
  require 'shadow'
  require 'augeas'
  require 'sys/filesystem'
  require 'tmpdir'
  require 'fileutils'
  require 'json'

  raise 'Expected OpenVox behind require puppet' unless Gem.loaded_specs.key?('openvox')

  required = ['app-admin/openvox', 'dev-ruby/ruby-shadow', 'dev-ruby/ruby-augeas', 'dev-ruby/sys-filesystem']
  world = File.readlines('/var/lib/portage/world', chomp: true)
  missing = required - world
  raise "Runtime packages missing from world: #{missing.join(', ')}" unless missing.empty?

  os = Facter.value(:os)
  raise 'Cannot collect Gentoo OS facts' unless os && os['family'] == 'Gentoo'
  mounts = Facter.value(:mountpoints)
  raise 'Cannot collect root mount facts' unless mounts && mounts.key?('/')
  raise 'Cannot stat root filesystem' unless Sys::Filesystem.stat('/').block_size.positive?

  raise 'Puppet shadow feature unavailable' unless Puppet.features.libshadow?
  user_provider = Puppet::Type.type(:user).provider(:useradd)
  raise 'User provider cannot manage password age' unless user_provider.manages_password_age?
  root = Puppet::Type.type(:user).new(name: 'root', provider: :useradd).provider
  raise 'User provider cannot query root' unless root.exists? && root.uid.to_i.zero?
  raise 'User provider cannot read shadow age' unless root.password_max_age.is_a?(Integer)

  Dir.mktmpdir('stage0-runtime-', '/var/tmp') do |dir|
    FileUtils.mkdir_p("#{dir}/etc")
    File.write("#{dir}/etc/hosts", "127.0.0.1 localhost\n")
    aug = Augeas.open(dir, nil, Augeas::NO_MODL_AUTOLOAD)
    begin
      aug.set('/augeas/load/Hosts/lens', 'Hosts.lns')
      aug.set('/augeas/load/Hosts/incl', '/etc/hosts')
      aug.load
      raise 'Augeas cannot parse Hosts lens' unless aug.get('/files/etc/hosts/1/canonical') == 'localhost'
      aug.set('/files/etc/hosts/1/alias', 'stage0-runtime')
      raise 'Augeas cannot save Hosts lens' unless aug.save
      aug.load
      raise 'Augeas lens round trip failed' unless aug.get('/files/etc/hosts/1/alias') == 'stage0-runtime'
    ensure
      aug.close
    end
  end

  puts JSON.generate(
    readiness: 'passed',
    ruby: RUBY_VERSION,
    interpreter: File.realpath('/usr/bin/ruby'),
    openvox: Gem.loaded_specs['openvox'].version.to_s,
    os: os['family'],
    checks: ['world', 'imports', 'os_fact', 'mountpoints_fact', 'filesystem_stat', 'useradd_shadow', 'augeas_lens_round_trip'],
  )
end
