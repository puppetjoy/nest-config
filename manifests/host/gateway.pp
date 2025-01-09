class nest::host::gateway {
  nest::lib::package { 'app-crypt/certbot':
    ensure => installed,
  }
}
