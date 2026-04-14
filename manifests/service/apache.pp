class nest::service::apache (
  Boolean $manage_firewall = false,
  Array[String[1]] $service_after = [],
  Array[String[1]] $service_requires = [],
) {
  nest::lib::srv { 'www': }

  include 'apache'
  $apache_service_name = $apache::params::service_name

  if !empty($service_after) or !empty($service_requires) {
    $apache_service_unit_dropin = @("END_UNIT")
      [Unit]
      ${$service_requires.map |$unit| { "Requires=${unit}" }.join("\n")}
      ${$service_after.map |$unit| { "After=${unit}" }.join("\n")}
      | END_UNIT

    file { "/etc/systemd/system/${apache_service_name}.service.d":
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    }

    file { "/etc/systemd/system/${apache_service_name}.service.d/10-requires-mounts-for.conf":
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => $apache_service_unit_dropin,
      notify  => Nest::Lib::Systemd_reload['apache'],
    }

    nest::lib::systemd_reload { 'apache': }

    Nest::Lib::Systemd_reload['apache'] ~> Class['apache::service']
  }

  # I don't use this command, and it doesn't work on systemd systems, but the
  # apache_version fact depends on being able to run this with the `-v`
  # argument, so just make it work.
  file { '/usr/sbin/apache2ctl':
    ensure  => link,
    target  => '/usr/sbin/apache2',
    require => Class['apache'],
  }

  # Include required modules
  apache::mod { 'log_config': }
  apache::mod { 'unixd': }

  nest::lib::package_use { 'httpd':
    package => 'www-servers/apache',
    use     => [
      'apache2_modules_access_compat',
      'apache2_modules_lbmethod_byrequests',
      'apache2_modules_log_forensic',
      'apache2_modules_proxy',
      'apache2_modules_proxy_balancer',
      'apache2_modules_proxy_fcgi',
      'apache2_modules_proxy_http',
      'apache2_modules_proxy_wstunnel',
      'apache2_modules_slotmem_shm', # for proxy_balancer
      'threads',
    ],
  }

  # This is not at all necessary, but the default defines are not used
  # by puppetlabs/apache and it could lead to confusion.
  file_line { 'apache2-opts':
    path    => '/etc/conf.d/apache2',
    line    => 'APACHE2_OPTS=',
    match   => '^#?APACHE2_OPTS=',
    require => Class['apache'],
    notify  => Class['apache::service'],
  }

  if $manage_firewall {
    nest::lib::external_service { ['http', 'https']: }
  }
}
