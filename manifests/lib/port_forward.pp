define nest::lib::port_forward (
  Stdlib::Port                      $port,
  Enum['tcp', 'udp']                $proto,
  Stdlib::IP::Address::V4           $to_addr,
  Stdlib::Port                      $to_port,
  Optional[Stdlib::IP::Address::V4] $dest       = undef,
  Boolean                           $loopback   = true,
  Optional[String]                  $masquerade = undef,
  String                            $zone       = 'external',
) {
  firewalld_rich_rule { $name:
    zone         => $zone,
    family       => ipv4,
    dest         => $dest,
    forward_port => {
      port     => $port,
      protocol => $proto,
      to_addr  => $to_addr,
      to_port  => $to_port,
    },
  }

  if $loopback {
    if $dest {
      $dest_args = "-d ${dest} "
    } else {
      $dest_args = ''
    }

    firewalld_direct_rule { "${name}-loopback":
      inet_protocol => ipv4,
      table         => nat,
      chain         => 'OUTPUT',
      priority      => 10,
      args          => "${dest_args}-p ${proto} --dport ${port} -j DNAT --to-destination ${to_addr}:${to_port}",
    }
  }

  if $masquerade {
    firewalld_direct_rule { "${name}-masquerade":
      inet_protocol => ipv4,
      table         => nat,
      chain         => 'POSTROUTING',
      priority      => 10,
      args          => "-o ${masquerade} -p ${proto} --dport ${to_port} -d ${to_addr} -j MASQUERADE",
    }
  }
}
