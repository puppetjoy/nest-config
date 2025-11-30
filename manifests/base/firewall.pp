class nest::base::firewall {
  case $facts['os']['family'] {
    'Gentoo': {
      if $facts['networking']['interfaces'] {
        # Keep this filter list in sync with systemd-networkd's 20-ethernet.network
        $external_interfaces = $nest::external_interfaces.reduce(
          $facts['networking']['interfaces'].keys.filter |$i| {
            $i =~ /^(bond|br|en|eth|usb|wlan)/
          }
        ) |$memo, $i| {
          $i ? {
            /^-(.*)/ => $memo - $1,
            default  => $memo.union([$i]),
          }
        }.sort
      } else {
        $external_interfaces = []
      }

      # Disable iptables-legacy and use the nftables backend...
      # firewalld and most tools use nftables natively; calico still calls iptables to clean up
      exec { 'eselect-iptables-nft':
        command => '/usr/bin/eselect iptables set xtables-nft-multi',
        unless  => '/usr/bin/eselect iptables show | /bin/grep xtables-nft-multi',
      }

      class { 'firewalld':
        default_zone => 'drop',
      }

      # Don't manage the service state
      Service <| title == 'firewalld' |> {
        ensure => undef,
      }

      # Configure the zones that this module uses
      firewalld_zone {
        'external':
          interfaces => $external_interfaces,
          masquerade => true, # for NAT
          target     => 'DROP',
        ;

        'internal':
          sources => '172.16.0.0/12',
          target  => 'ACCEPT',
        ;

        'home':
          sources => '172.22.1.0/24',
          target  => 'default',
        ;
      }

      firewalld_policy { 'nat':
        ensure        => present,
        ingress_zones => 'internal',
        egress_zones  => 'external',
        target        => 'ACCEPT',
      }

      # Purge direct rules
      firewalld_direct_purge { 'rule': }

      # Purge unmanaged zones
      tidy { '/etc/firewalld/zones':
        matches => [
          'block.xml*',
          'dmz.xml*',
          'drop.xml*',
          'public.xml*',
          'trusted.xml*',
          'work.xml*',
          'kubernetes.xml*',
        ],
        recurse => 1,
        notify  => Class['firewalld::reload'],
      }
    }

    'windows': {
      class { 'windows_firewall':
        ensure => running,
      }

      windows_firewall::exception {
        default:
          ensure   => present,
          protocol => 'ICMPv4',
          action   => allow;
        'nest-vpn-icmp':
          display_name => 'Nest VPN ICMP',
          description  => 'Allow pings from Nest VPN',
          remote_ip    => '172.22.0.0/24';
        'nest-secure-icmp':
          display_name => 'Nest Secure ICMP',
          description  => 'Allow pings from Nest secure network',
          remote_ip    => '172.22.4.0/24',
        ;
      }
    }
  }
}
