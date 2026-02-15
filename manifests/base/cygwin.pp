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

  # Exclude key Cygwin startup binaries to reduce Defender overhead during
  # terminal and tmux cold starts.
  exec { 'windows-defender-exclude-cygwin-zsh':
    command  => 'Add-MpPreference -ExclusionProcess "C:\tools\cygwin\bin\zsh.exe"',
    unless   => 'if ((Get-MpPreference)."ExclusionProcess" -notcontains "C:\tools\cygwin\bin\zsh.exe") { exit 1 }',
    provider => powershell,
    require  => File['C:/tools/cygwin'],
  }

  exec { 'windows-defender-exclude-cygwin-tmux':
    command  => 'Add-MpPreference -ExclusionProcess "C:\tools\cygwin\bin\tmux.exe"',
    unless   => 'if ((Get-MpPreference)."ExclusionProcess" -notcontains "C:\tools\cygwin\bin\tmux.exe") { exit 1 }',
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
    find "$(cygpath -am /)" -not -path "$(cygpath -am /home)/*" -not -path "*/dev/*" -not -path "*/tmp/*" |
      xargs cygpath | xargs chown -h Administrators:None
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
