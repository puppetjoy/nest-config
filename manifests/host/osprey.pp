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

  # This is host-specific suspend/resume tuning for osprey's NVIDIA dGPU.
  # Keep it out of the shared GPU path until S0ix is proven safe for all
  # NVIDIA systems in the nest.
  file_line { 'nvidia.conf-enable-s0ix-power-management':
    path  => '/etc/modprobe.d/nvidia.conf',
    line  => "  NVreg_EnableS0ixPowerManagement=1 \\",
    match => '^\\s*NVreg_EnableS0ixPowerManagement=',
    after => '^options nvidia \\$',
  }
  ~> Class['nest::base::dracut']

  file { '/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold':
    mode   => '0755',
    source => 'puppet:///modules/nest/host/osprey/prune-misplaced-nvidia-s0ix-vram-threshold.rb',
  }

  # file_line replaces a matching line in place, so prune any copy outside the
  # options block before ensuring the desired line at its package-owned anchor.
  exec { 'prune-misplaced-nvidia-s0ix-vram-threshold':
    command => '/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold /etc/modprobe.d/nvidia.conf',
    onlyif  => '/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold --check /etc/modprobe.d/nvidia.conf',
    require => [
      File['/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold'],
      File_line['nvidia.conf-enable-s0ix-power-management'],
    ],
  }
  ~> Class['nest::base::dracut']

  file_line { 'nvidia.conf-s0ix-vram-threshold':
    path    => '/etc/modprobe.d/nvidia.conf',
    line    => "  NVreg_S0ixPowerManagementVideoMemoryThreshold=10000 \\",
    match   => '^\\s*NVreg_S0ixPowerManagementVideoMemoryThreshold=',
    # Anchor to a package-provided line that exists before this catalog runs.
    # file_line providers cache the file independently, so anchoring to the
    # S0ix line managed above can append this line at EOF on the first run.
    after   => '^\\s*NVreg_PreserveVideoMemoryAllocations=1 \\$',
    require => Exec['prune-misplaced-nvidia-s0ix-vram-threshold'],
  }
  ~> Class['nest::base::dracut']
}
