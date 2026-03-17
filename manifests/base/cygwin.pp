class nest::base::cygwin {
  package { 'cygwin':
    ensure => installed,
  }

  # Ensure any files managed under the cygwin root implicitcly depend on
  # Package[cygwin]
  file { 'C:/tools/cygwin':
    require => Package['cygwin'],
  }

  # Disable performance-crippling real-time scanning of cygwin
  exec { 'windows-defender-exclude-cygwin':
    command  => 'Add-MpPreference -ExclusionPath "C:\tools\cygwin"',
    unless   => 'if ((Get-MpPreference)."ExclusionPath" -notcontains "C:\tools\cygwin") { exit 1 }',
    provider => powershell,
    require  => File['C:/tools/cygwin'],
  }


  #
  # Deterministic Permissions
  #
  # Cygwin sets file ownership to whoever installs it, which may be me or
  # SYSTEM depending on how Puppet runs.  Reassign such files to the
  # Administrators group.
  #
  $fix_perms_content = @(END_FIX_PERMS)
    #!/bin/bash
    find /bin /etc /lib /sbin /usr /var \
      \( -type f -o -type d \) \
      -not -path /etc/hosts \
      -not -path /etc/mtab \
      -not -path /etc/networks \
      -not -path /etc/protocols \
      -not -path /etc/services \
      -not -path /usr/share/fonts/microsoft \
      -not -path /usr/share/fonts/microsoft/* \
      -print0 |
      xargs -0 chown Administrators:None
    | END_FIX_PERMS

  file { 'C:/tools/cygwin/etc/postinstall/zp_fix-perms.sh':
    mode    => '0755',
    owner   => 'Administrators',
    group   => 'None',
    content => $fix_perms_content,
  }

  exec { 'cygwin-fix-perms':
    command     => shellquote(
      'C:/tools/cygwin/bin/bash.exe', '-c',
      'source /etc/profile && /etc/postinstall/zp_fix-perms.sh'
    ),
    refreshonly => true,
    subscribe   => File['C:/tools/cygwin/etc/postinstall/zp_fix-perms.sh'],
  }


  #
  # Cygserver Config
  #
  package { 'cygrunsrv':
    ensure   => installed,
    provider => 'cygwin',
    require  => Package['cygwin'],
  }

  exec { 'cygserver-config':
    command => shellquote(
      'C:/tools/cygwin/bin/bash.exe', '-c',
      'source /etc/profile && /usr/bin/cygserver-config --yes'
    ),
    creates => 'C:/tools/cygwin/etc/cygserver.conf',
    require => Package['cygrunsrv'],
    notify  => Service['cygserver'],
  }

  service { 'cygserver':
    ensure  => running,
    enable  => true,
    require => Exec['cygserver-config'],
  }

  Class['nest::base::cygwin']
  -> Package <| provider == 'cygwin' and title != 'cygrunsrv' |>
}
