class nest::base::autofs {
  file_line { 'auto_master-/nest':
    path   => '/etc/auto_master',
    line   => '/nest auto_nest',
    match  => '^/nest\s+',
    notify => Exec['automount-reload'],
  }

  file { '/etc/auto_nest':
    mode    => '0644',
    owner   => 'root',
    group   => 'wheel',
    content => "home -fstype=nfs,noappledouble,noowners,resvport,vers=4 ${nest::nestfs_hostname}:/nest/home\n",
    notify  => Exec['automount-reload'],
  }

  exec { 'automount-reload':
    command     => '/usr/sbin/automount -vc',
    refreshonly => true,
  }
}
