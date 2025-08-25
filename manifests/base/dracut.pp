class nest::base::dracut {
  tag 'boot'
  tag 'kernel'

  Class[
    'nest::base::branding', # /etc/os-release, etc
    'nest::base::zfs',      # zpool.cache, etc
  ] ~> Class['nest::base::dracut']

  # For securing emergency shell
  User['root'] ~> Class['nest::base::dracut']

  if $facts['force_kernel_install'] {
    notify { 'forcing-kernel-install': }
  }

  nest::lib::package { 'sys-kernel/dracut':
    ensure => installed,
  }

  if $facts['profile']['architecture'] == 'amd64' {
    nest::lib::package { 'sys-firmware/intel-microcode':
      ensure => installed,
    }
  }

  # Prefer fast zstd except on low memory arm devices
  $compress = $facts['profile']['architecture'] ? {
    'arm'   => 'gzip',
    default => 'zstd',
  }

  if $facts['profile']['platform'] == 'live' {
    $base_config_content = @(EOT)
      add_dracutmodules+=" dmsquash-live "
      omit_dracutmodules+=" zfs "
      kernel_cmdline="rd.live.overlay.overlayfs=1"
      | EOT

    # Install dmsetup(8) for dmsquash-live
    nest::lib::package { 'sys-fs/lvm2':
      ensure => installed,
    }
  } elsif $facts['build'] and $facts['build'] != 'kernel' {
    $base_config_content = ''
  } else {
    $base_config_content = @("EOT")
      compress="${compress}"
      force="yes"
      hostonly="yes"
      omit_dracutmodules+=" nfs "
      | EOT
  }

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/dracut.conf.d':
      ensure => directory,
    ;

    '/etc/dracut.conf.d/00-base.conf':
      content => $base_config_content,
    ;
  }

  # Add delay to ensure all devices are enumerated at boot before the ZFS import
  # See: https://github.com/openzfs/zfs/issues/8885#issuecomment-774503341
  # XXX remove systemd-executor item upon fix upstream
  $systemd_udev_settle_sleep = @(END_DROPIN)
    [Service]
    ExecStartPre=/bin/sleep 5
    | END_DROPIN
  $install_config = @(END_CONF)
    install_items+=" /etc/systemd/system/systemd-udev-settle.service.d/10-sleep.conf /usr/lib/systemd/systemd-executor "
    | END_CONF

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/systemd/system/systemd-udev-settle.service.d':
      ensure => directory,
    ;

    '/etc/systemd/system/systemd-udev-settle.service.d/10-sleep.conf':
      content => $systemd_udev_settle_sleep,
      notify  => Nest::Lib::Systemd_reload['dracut'],
    ;

    '/etc/dracut.conf.d/10-systemd.conf':
      content => $install_config,
    ;
  }

  nest::lib::systemd_reload { 'dracut': }
}
