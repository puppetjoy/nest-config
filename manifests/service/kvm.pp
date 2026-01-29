class nest::service::kvm (
  Boolean $server = true,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { 'gui-apps/input-leap':
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
      package { 'input-leap':
        ensure => installed,
      }
    }
  }
}
