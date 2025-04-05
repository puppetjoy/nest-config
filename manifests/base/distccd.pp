class nest::base::distccd {
  file { '/etc/systemd/system/distccd.service.d/00gentoo.conf':
    ensure => absent,
  }

  file { '/etc/systemd/system/distccd.service.d/10-allowed-servers.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => "[Service]\nEnvironment=\"ALLOWED_SERVERS=172.22.0.0/16\"\n",
  }
  ~>
  nest::lib::systemd_reload { 'distccd': }
  ~>
  service { 'distccd':
    enable => $nest::distcc_server,
  }

  if $nest::distcc_server {
    nest::lib::package { 'llvm-core/clang':
      ensure => installed,
    }

    exec { 'update-distcc-compiler-links':
      command     => '/usr/bin/eselect compiler-shadow update',
      refreshonly => true,
    }
  }
}
