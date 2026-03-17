class nest::base::fs {
  nest::lib::package { 'net-fs/nfs-utils':
    ensure => installed,
  }

  if $nest::fileserver {
    service { 'nfs-server':
      enable => true,
    }

    service { 'zfs-share':
      enable  => true,
      require => Package['sys-fs/zfs'],
    }

    nest::lib::package { 'net-fs/samba':
      ensure => installed,
    }

    file { '/var/lib/samba/usershares':
      ensure  => directory,
      mode    => '1755',
      owner   => 'root',
      group   => 'root',
      require => Package['net-fs/samba'],
    }

    $samba_config = @("EOT")
      [global]
        unix extensions = no

      [homes]
        comment = Home Directories
        browseable = no
        read only = no

      [nest]
        path = /nest
        browseable = yes
        read only = no
        valid users = ${nest::user}
      | EOT

    file { '/etc/samba/smb.conf':
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => $samba_config,
      require => File['/var/lib/samba/usershares'],
    }

    service { 'smb':
      enable    => true,
      subscribe => File['/etc/samba/smb.conf'],
    }
  }

  if $nest::fscache {
    nest::lib::package { 'sys-fs/cachefilesd':
      ensure => installed,
    }

    $cachefilesd_requires_mounts_for = @(EOT)
      [Unit]
      RequiresMountsFor=/var/cache/fscache
      | EOT

    file { '/etc/systemd/system/cachefilesd.service.d':
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    }

    file { '/etc/systemd/system/cachefilesd.service.d/10-requires-mounts-for.conf':
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => $cachefilesd_requires_mounts_for,
      notify  => Nest::Lib::Systemd_reload['cachefilesd'],
      require => Package['sys-fs/cachefilesd'],
    }

    ::nest::lib::systemd_reload { 'cachefilesd': }

    service { 'cachefilesd':
      enable  => true,
      require => Nest::Lib::Systemd_reload['cachefilesd'],
    }
  } else {
    service { 'cachefilesd':
      enable => false,
    }
    ->
    file { '/etc/systemd/system/cachefilesd.service.d':
      ensure => absent,
      force  => true,
    }
    ->
    nest::lib::package { 'sys-fs/cachefilesd':
      ensure => absent,
    }
  }
}
