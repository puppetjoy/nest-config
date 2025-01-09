class nest::host::runner2 {
  class { 'nest::service::dnsmasq':
    interfaces => ['usb0'],
  }

  # Hand out IPs in order, but start over every reboot
  $dnsmasq_conf = @(DNSMASQ)
    dhcp-leasefile=/run/dnsmasq.leases
    dhcp-range=172.22.99.100,172.22.99.199,infinite
    dhcp-sequential-ip
    dhcp-option=option:classless-static-route,0.0.0.0/0,172.22.99.1,172.22.4.0/24,172.22.99.1
    | DNSMASQ

  file { '/etc/dnsmasq.d/dhcp.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $dnsmasq_conf,
    notify  => Service['dnsmasq'],
  }

  Firewalld_zone <| title == 'internal' |> {
    masquerade => true,
  }

  firewalld_service { ['dhcp', 'dns']:
    ensure => present,
    zone   => external,
  }
}
