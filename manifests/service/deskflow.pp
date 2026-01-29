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
      # Horizontal scroll bug
      # package { 'deskflow':
      package { 'barrier':
        ensure => installed,
      }
    }
  }
}
