class nest::host::hawk {
  package_accept_keywords { [
    'app-emulation/vagrant',
    'dev-cpp/abseil-cpp',
    'dev-libs/protobuf',
    'dev-ruby/google-protobuf',
    'dev-ruby/googleapis-common-protos-types',
    'dev-ruby/grpc',
    'dev-ruby/hashicorp-checkpoint',
    'dev-ruby/ipaddr',
    'dev-ruby/jwt',
    'dev-ruby/oauth2',
    'dev-ruby/pairing_heap',
    'dev-ruby/rgl',
    'dev-ruby/snaky_hash',
    'dev-ruby/stream',
    'dev-ruby/vagrant_cloud',
    'dev-ruby/version_gem',
  ]:
    tag => 'profile',
  }
  ->
  nest::lib::package { 'app-emulation/vagrant':
    ensure => installed,
  }

  firewalld_direct_chain { 'LIBVIRT_FWX':
    inet_protocol => ipv4,
    table         => filter,
  }
  ->
  firewalld_direct_rule {
    default:
      inet_protocol => ipv4,
      table         => filter,
      chain         => 'LIBVIRT_FWX', # applies before LIBVIRT_FWI
      priority      => 0,
    ;

    'puppet':
      args => '-d 10.81.40.10 -p tcp --dport 8140 -j ACCEPT',
    ;

    'orchestrator':
      args => '-d 10.81.40.10 -p tcp --dport 8142 -j ACCEPT',
    ;

    # 'cd4pe':
    #   args => '-d 10.81.40.11 -p tcp --dport 8000 -j ACCEPT',
    # ;

    # 'influxdb':
    #   args => '-d 10.81.40.13 -p tcp --dport 8086 -j ACCEPT',
    # ;
  }

  # For port forwarding into VMs
  Firewalld_zone <| title == 'libvirt' |> {
    masquerade => true,
  }
}
