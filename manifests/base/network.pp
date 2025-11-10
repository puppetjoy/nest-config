class nest::base::network {
  # Bridging is a layer 2 activity
  # See: https://wiki.libvirt.org/Net.bridge.bridge-nf-call_and_sysctl.conf.html
  sysctl { [
    'net.bridge.bridge-nf-call-arptables',
    'net.bridge.bridge-nf-call-ip6tables',
    'net.bridge.bridge-nf-call-iptables',
  ]:
    ensure => present,
    value  => '0',
  }

  file { '/etc/systemd/network':
    ensure       => directory,
    mode         => '0644',
    owner        => root,
    group        => root,
    purge        => true,
    recurse      => true,
    force        => true,
    source       => [
      'puppet:///modules/nest/private/network',
      'puppet:///modules/nest/network',
    ],
    sourceselect => all,
  }
  ->
  file_line { 'systemd-networkd-disable-ManageForeignRoutingPolicyRules':
    path  => '/etc/systemd/networkd.conf',
    line  => 'ManageForeignRoutingPolicyRules=no',
    match => '^#?ManageForeignRoutingPolicyRules=',
  }
  ~>
  service { 'systemd-networkd':
    enable => true,
  }

  unless $facts['is_container'] {
    exec { 'systemd-networkd-reload':
      command     => '/bin/networkctl reload',
      onlyif      => '/bin/systemctl is-active systemd-networkd',
      refreshonly => true,
      subscribe   => File['/etc/systemd/network'],
      before      => Service['systemd-networkd'],
    }
  }

  if $nest::wifi {
    $wait_for_any_online = @(WAIT)
      [Service]
      ExecStart=
      ExecStart=/lib/systemd/systemd-networkd-wait-online --any
      | WAIT

    file {
      default:
        mode  => '0644',
        owner => 'root',
        group => 'root',
      ;

      '/etc/systemd/system/systemd-networkd-wait-online.service.d':
        ensure => directory,
      ;

      '/etc/systemd/system/systemd-networkd-wait-online.service.d/10-wait-for-any.conf':
        content => $wait_for_any_online,
      ;
    }
    ~>
    nest::lib::systemd_reload { 'network': }
  } else {
    file { '/etc/systemd/system/systemd-networkd-wait-online.service.d':
      ensure => absent,
      force  => true,
    }
    ~>
    nest::lib::systemd_reload { 'network': }
  }
}
