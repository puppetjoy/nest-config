class nest::base::fstab {
  $hostname = regsubst($::trusted['certname'], '\..*', '')

  $suffix = $hostname ? {
    /(\d+)$/ => $1,
    default  => '',
  }

  if length($hostname) > 8 {
    $labelname = "${hostname[0,8 - $suffix.length]}${suffix}"
  } else {
    $labelname = $hostname
  }

  $specs = {
    'boot'    => [
      "set 1/spec PARTLABEL=${hostname}-boot",
      'set 1/file /boot',
      'set 1/vfstype vfat',
      'set 1/opt defaults',
      'set 1/dump 0',
      'set 1/passno 2',
    ],

    'boot-mbr' => [
      "set 1/spec LABEL=${labelname}-bt",
      'set 1/file /boot',
      'set 1/vfstype vfat',
      'set 1/opt defaults',
      'set 1/dump 0',
      'set 1/passno 2',
    ],

    'efi'     => [
      "set 2/spec PARTLABEL=${hostname}-efi",
      'set 2/file /efi',
      'set 2/vfstype vfat',
      'set 2/opt defaults',
      'set 2/dump 0',
      'set 2/passno 2',
    ],

    'swap'    => [
      "set 3/spec LABEL=${labelname}-swap",
      'set 3/file none',
      'set 3/vfstype swap',
      'set 3/opt discard',
      'set 3/dump 0',
      'set 3/passno 0',
    ],

    'var'     => [
      'set 4/spec none',
      'set 4/file /var',
      'set 4/vfstype none',
      'set 4/opt[1] fake',
      'set 4/opt[2] noauto',
      'set 4/opt[3] x-systemd.requires',
      'set 4/opt[3]/value zfs-mount.service',
      'set 4/dump 0',
      'set 4/passno 0',
    ],

    'nest-fscache' => [
      "set 5/spec LABEL=${labelname}-fscache",
      'set 5/file /var/cache/fscache',
      'set 5/vfstype ext4',
      'set 5/opt[1] defaults',
      'set 5/opt[2] discard',
      'set 5/dump 0',
      'set 5/passno 2',

      "set 6/spec ${nest::nestfs_hostname}:/nest",
      'set 6/file /nest',
      'set 6/vfstype nfs',
      'set 6/opt[1] fsc',
      'set 6/opt[2] x-systemd.automount',
      'set 6/opt[3] x-systemd.requires',
      'set 6/opt[3]/value cachefilesd.service',

      $nest::vpn_client ? {
        true    => [
          'set 6/opt[4] x-systemd.requires',
          'set 6/opt[4]/value openvpn-client@nest.service',
          'set 6/opt[5] x-systemd.requires',
          'set 6/opt[5]/value sys-subsystem-net-devices-tun0.device',
        ],
        default => [],
      },

      'set 6/dump 0',
      'set 6/passno 0',
    ],

    'nest-nocache' => [
      "set 6/spec ${nest::nestfs_hostname}:/nest",
      'set 6/file /nest',
      'set 6/vfstype nfs',
      'set 6/opt[1] x-systemd.automount',

      $nest::vpn_client ? {
        true    => [
          'set 6/opt[2] x-systemd.requires',
          'set 6/opt[2]/value openvpn-client@nest.service',
          'set 6/opt[3] x-systemd.requires',
          'set 6/opt[3]/value sys-subsystem-net-devices-tun0.device',
        ],
        default => [],
      },

      'set 6/dump 0',
      'set 6/passno 0',
    ],

    'falcon' => [
      'set 7/spec falcon.nest:/falcon',
      'set 7/file /falcon',
      'set 7/vfstype nfs',
      'set 7/opt[1] x-systemd.automount',

      $nest::vpn_client ? {
        true    => [
          'set 7/opt[2] x-systemd.requires',
          'set 7/opt[2]/value openvpn-client@nest.service',
          'set 7/opt[3] x-systemd.requires',
          'set 7/opt[3]/value sys-subsystem-net-devices-tun0.device',
        ],
        default => [],
      },

      'set 7/dump 0',
      'set 7/passno 0',
    ],
  }

  $boot_spec = $facts['profile']['platform'] ? {
    'radxazero' => 'boot-mbr',
    default     => 'boot',
  }

  if $nest::fscache {
    $nest_spec   = 'nest-fscache'
    $falcon_spec = 'falcon'
  } else {
    $nest_spec   = 'nest-nocache'
    $falcon_spec = 'falcon'
  }

  if $nest::nestfs_hostname == "${hostname}.nest" {
    $fstab = $specs[$boot_spec] + $specs['swap'] + $specs['var']
  } elsif $facts['mountpoints']['/efi'] {
    $fstab = $specs[$boot_spec] + $specs['efi'] + $specs['swap'] + $specs['var'] + $specs[$nest_spec] + $specs[$falcon_spec]
  } else {
    $fstab = $specs[$boot_spec] + $specs['swap'] + $specs['var'] + $specs[$nest_spec] + $specs[$falcon_spec]
  }

  augeas { 'fstab':
    context => '/files/etc/fstab',
    changes => ['rm *[spec]'] + $fstab.flatten,
  }

  # XXX: Hide harmless error at shutdown when trying to unmount /var due to
  # journald still writing to /var/log/journal
  # See: https://github.com/systemd/systemd/issues/867
  $var_lazy_unmount = @(END_OVERRIDE)
    [Mount]
    LazyUnmount=yes
    | END_OVERRIDE

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/systemd/system/var.mount.d':
      ensure => directory,
    ;

    '/etc/systemd/system/var.mount.d/lazyunmount.conf':
      ensure => absent,
    ;

    '/etc/systemd/system/var.mount.d/10-lazy-unmount.conf':
      content => $var_lazy_unmount,
      notify  => Nest::Lib::Systemd_reload['fstab'],
    ;
  }

  ::nest::lib::systemd_reload { 'fstab': }
}
