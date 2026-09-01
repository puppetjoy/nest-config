class nest::host::osprey {
  # GNOME 48's ordinary gtk-launch path did not apply the switcheroo-control
  # environment from PrefersNonDefaultGPU, so keep the hint and use the native
  # switcheroo launcher as a fallback for the executable path.
  $resolve_desktop_entry = @("END")
    [Desktop Entry]
    Version=1.0
    Type=Application
    Name=DaVinci Resolve
    GenericName=DaVinci Resolve
    Comment=Revolutionary new tools for editing, visual effects, color correction and professional audio post production, all in a single application!
    Path=/opt/resolve/
    Exec=/usr/sbin/switcherooctl launch /usr/bin/env ALSA_CONFIG_PATH=/etc/alsa/resolve.conf /opt/resolve/bin/resolve %u
    Terminal=false
    PrefersNonDefaultGPU=true
    MimeType=application/x-resolveproj;
    Icon=/opt/resolve/graphics/DV_Resolve.png
    StartupWMClass=resolve
    StartupNotify=true
    Name[en_US]=DaVinci Resolve
    | END

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

  # Fairlight probes the generic dmix PCM even when Resolve's speaker setup
  # selects the ALC294 codec. On osprey card 0 is the NVIDIA HDMI controller,
  # which has no PCM device 0, so route only Resolve's ALSA namespace through
  # the already-running PipeWire graph instead of changing global card order.
  file { '/etc/alsa':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
  }

  file { '/etc/alsa/resolve.conf':
    ensure  => file,
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/alsa/resolve.conf',
    require => File['/etc/alsa'],
  }

  file { '/usr/local/share/applications/com.blackmagicdesign.resolve.desktop':
    ensure  => file,
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $resolve_desktop_entry,
    require => [
      File['/etc/alsa/resolve.conf'],
      File['/usr/local/share/applications'],
    ],
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

  file_line { 'nvidia.conf-s0ix-vram-threshold':
    path    => '/etc/modprobe.d/nvidia.conf',
    line    => "  NVreg_S0ixPowerManagementVideoMemoryThreshold=10000 \\",
    match   => '^\\s*NVreg_S0ixPowerManagementVideoMemoryThreshold=',
    # Anchor to a package-provided line that exists before this catalog runs.
    # file_line providers cache the file independently, so anchoring to the
    # S0ix line managed above can append this line at EOF on the first run.
    after   => '^\\s*NVreg_PreserveVideoMemoryAllocations=1 \\$',
    require => File_line['nvidia.conf-enable-s0ix-power-management'],
  }
  ~> Class['nest::base::dracut']
}
