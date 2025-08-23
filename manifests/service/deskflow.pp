class nest::service::deskflow (
  Boolean $server = true,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { 'gui-apps/deskflow':
        ensure => installed,
        use    => '-gui',
      }

      if $server {
        firewalld_service { 'synergy':
          ensure => present,
          zone   => 'libvirt',
        }
      }
    }

    'windows': {
      package { 'deskflow':
        ensure => installed,
      }
    }
  }
}
