class nest::host::osprey {
  $touchpad_jitter_hwdb = @("END")
    # Increase touchpad hysteresis to ignore small hand tremors while
    # pausing a two-finger scroll gesture.
    evdev:name:ASCF1A00:00 2808:0220 Touchpad:dmi:*:svnASUSTeKCOMPUTERINC.:pnProArtPX13HN7306WU_HN7306WU:*
     EVDEV_ABS_00=:::8
     EVDEV_ABS_01=:::8
     EVDEV_ABS_35=:::8
     EVDEV_ABS_36=:::8
    | END

  file { '/etc/udev/hwdb.d':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
  }

  file { '/etc/udev/hwdb.d/90-nest-touchpad-jitter.hwdb':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $touchpad_jitter_hwdb,
    require => File['/etc/udev/hwdb.d'],
    notify  => Exec['systemd-hwdb-update-osprey-touchpad'],
  }

  exec { 'systemd-hwdb-update-osprey-touchpad':
    command     => '/usr/sbin/systemd-hwdb update',
    refreshonly => true,
  }
  ~>
  exec { 'udevadm-trigger-osprey-touchpad':
    command     => '/usr/sbin/udevadm trigger --subsystem-match=input --action=change',
    refreshonly => true,
  }
}
