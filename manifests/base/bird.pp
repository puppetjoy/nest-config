class nest::base::bird {
  if $nest::bird_role {
    $bird_role = $nest::bird_role
  } elsif !$nest::vpn {
    $bird_role = 'client'
  } else {
    $bird_role = undef
  }

  if $bird_role {
    $router_id = pick_default($nest::fixed_ips[$trusted['certname']], $nest::host_records[$facts['fqdn']])

    # This class owns this config for now
    file {
      default:
        mode  => '0644',
        owner => 'root',
        group => 'root';
      '/etc/iproute2':
        ensure => directory;
      '/etc/iproute2/rt_tables':
        content => "100 bird\n",
      ;
    }

    nest::lib::package { 'net-misc/bird':
      ensure => installed,
    }
    ->
    file {
      default:
        mode  => '0644',
        owner => 'root',
        group => 'root',
      ;

      '/etc/bird.conf':
        content => epp('nest/bird/bird.conf.epp', { 'mode' => $bird_role, 'router_id' => $router_id }),
      ;

      '/etc/systemd/system/bird.service':
        source => 'puppet:///modules/nest/bird/bird.service',
      ;
    }
    ~>
    nest::lib::systemd_reload { 'bird': }
    ~>
    service { 'bird':
      enable => true,
    }
  } else {
    service { 'bird':
      ensure => stopped,
      enable => false,
    }
    ->
    file { [
      '/etc/bird.conf',
      '/etc/systemd/system/bird.service',
    ]:
      ensure => absent,
    }
    ->
    nest::lib::package { 'net-misc/bird':
      ensure => absent,
    }

    file { '/etc/iproute2':
      ensure => absent,
      force  => true,
    }
  }
}
