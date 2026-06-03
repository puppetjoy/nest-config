class nest::service::dnsmasq (
  Array[String] $interfaces      = [],
  Boolean       $bind_interfaces = false,
) {
  File {
    mode  => '0644',
    owner => 'root',
    group => 'root',
  }

  nest::lib::package { 'net-dns/dnsmasq':
    ensure => installed,
  }
  ->
  file_line { 'dnsmasq.conf-conf-dir':
    path  => '/etc/dnsmasq.conf',
    line  => 'conf-dir=/etc/dnsmasq.d/,*.conf',
    match => '^#?conf-dir=/etc/dnsmasq.d/,\*.conf',
  }
  ->
  file { '/etc/dnsmasq.d':
    ensure  => directory,
    require => File_line['dnsmasq.conf-conf-dir'],
  }
  ->
  service { 'dnsmasq':
    enable => true,
  }

  # Ensure dnsmasq can bind to its requested interfaces
  if $interfaces.empty {
    file { '/etc/dnsmasq.d/interfaces.conf':
      ensure => absent,
      notify => Service['dnsmasq'],
    }

    file { '/etc/systemd/system/dnsmasq.service.d':
      ensure => absent,
      force  => true,
      notify => Nest::Lib::Systemd_reload['dnsmasq'],
    }
  } else {
    $dnsmasq_interfaces = $interfaces.map |$i| { "interface=${i}" }.join("\n")
    $bind = $bind_interfaces ? { true => 'bind-interfaces', default => 'bind-dynamic' }
    $dnsmasq_interfaces_conf = @("END_CONF")
      ${dnsmasq_interfaces}
      ${bind}
      | END_CONF

    file { '/etc/dnsmasq.d/interfaces.conf':
      content => $dnsmasq_interfaces_conf,
      notify  => Service['dnsmasq'],
    }

    if $bind_interfaces {
      $systemd_device_units = $interfaces.map |$i| { "sys-subsystem-net-devices-${i}.device" }.join(' ')
      $dnsmasq_systemd_dropin_unit = @("END_UNIT")
        [Unit]
        Wants=systemd-resolved.service
        Requires=${systemd_device_units}
        After=systemd-resolved.service ${systemd_device_units}
        | END_UNIT

      file { '/etc/systemd/system/dnsmasq.service.d':
        ensure => directory,
        mode   => '0755',
      }

      file { '/etc/systemd/system/dnsmasq.service.d/10-interfaces.conf':
        mode    => '0644',
        content => $dnsmasq_systemd_dropin_unit,
        notify  => Nest::Lib::Systemd_reload['dnsmasq'],
      }
    } else {
      file { '/etc/systemd/system/dnsmasq.service.d':
        ensure => absent,
        force  => true,
        notify => Nest::Lib::Systemd_reload['dnsmasq'],
      }
    }
  }

  nest::lib::systemd_reload { 'dnsmasq':
    notify => Service['dnsmasq'],
  }
}
