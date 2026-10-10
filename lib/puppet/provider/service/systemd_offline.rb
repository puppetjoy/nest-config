# frozen_string_literal: true

Puppet::Type.type(:service).provide :systemd_offline, parent: :systemd do
  desc 'Manages systemd unit enablement in offline containers, without contacting a service manager.'

  commands systemctl: 'systemctl'
  confine is_container: true
  confine true: Puppet::FileSystem.exist?('/proc/1/comm') && !Puppet::FileSystem.read('/proc/1/comm').include?('systemd')

  # Inherit systemd enable/disable/mask semantics, but force filesystem mode.
  # Provider confines are not inherited; the live provider remains unchanged.
  def self.systemctl(*args)
    execute([command(:systemctl), '--root=/', *args])
  end

  def systemctl(*args)
    execute([command(:systemctl), '--root=/', *args])
  end

  def cached_enabled?
    return @cached_enabled if @cached_enabled

    result = execute([command(:systemctl), '--root=/', 'is-enabled', '--', @resource[:name]], failonfail: false)
    @cached_enabled = { output: result.chomp, exitcode: result.exitstatus }
  end

  def exist?
    cached_enabled?[:output] != 'not-found' && !cached_enabled?[:output].empty?
  end

  # A notification must not query a bus or start/restart anything in the image.
  def status
    :stopped
  end

  def start
    raise Puppet::Error, 'Cannot start services in an offline container'
  end

  def stop
    raise Puppet::Error, 'Cannot stop services in an offline container'
  end

  def restart
    raise Puppet::Error, 'Cannot restart services in an offline container'
  end
end
