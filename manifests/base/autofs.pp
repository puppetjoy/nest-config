class nest::base::autofs {
  file { '/Volumes/nest':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'wheel',
    notify => Exec['automount-reload'],
  }

  file_line { 'auto_master-/Volumes/nest':
    path   => '/etc/auto_master',
    line   => '/Volumes/nest auto_nest',
    match  => '^/Volumes/nest\s+',
    notify => Exec['automount-reload'],
  }

  file { '/etc/auto_nest':
    mode    => '0644',
    owner   => 'root',
    group   => 'wheel',
    content => "home -fstype=nfs,noowners,vers=4 ${nest::nestfs_hostname}:/nest/home\n",
    notify  => Exec['automount-reload'],
  }

  exec { 'automount-reload':
    command     => '/usr/sbin/automount -vc',
    refreshonly => true,
  }

  file { '/etc/synthetic.d':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'wheel',
  }

  file { '/etc/synthetic.d/nest.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'wheel',
    content => "nest\tVolumes/nest\n",
    require => File['/etc/synthetic.d'],
  }
}
