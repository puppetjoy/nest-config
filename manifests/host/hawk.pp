class nest::host::hawk (
  Sensitive[String[1]] $quill_gitlab_token,
  Sensitive[String[1]] $quill_gitlab_ssh_private_key,
  Sensitive[String[1]] $quill_gitlab_api_tunnel_ssh_private_key,
) {
  $quill_profile_dir        = "/home/${nest::user}/.hermes/profiles/quill"
  $quill_gitlab_dir         = "${quill_profile_dir}/gitlab"
  $quill_gitlab_ssh_dir     = "${quill_profile_dir}/.ssh"
  $quill_gitlab_token_value = $quill_gitlab_token.unwrap

  file { [
    "/home/${nest::user}/.hermes",
    "/home/${nest::user}/.hermes/profiles",
    $quill_profile_dir,
    $quill_gitlab_dir,
    $quill_gitlab_ssh_dir,
  ]:
    ensure => directory,
    mode   => '0700',
    owner  => $nest::user,
    group  => $nest::user,
  }

  file { "${quill_gitlab_dir}/api-token.header":
    ensure    => file,
    mode      => '0600',
    owner     => $nest::user,
    group     => $nest::user,
    content   => Sensitive("PRIVATE-TOKEN: ${quill_gitlab_token_value}\n"),
    show_diff => false,
    require   => File[$quill_gitlab_dir],
  }

  file { "${quill_gitlab_dir}/api-tunnel-id_ed25519":
    ensure    => file,
    mode      => '0600',
    owner     => $nest::user,
    group     => $nest::user,
    content   => $quill_gitlab_api_tunnel_ssh_private_key,
    show_diff => false,
    require   => File[$quill_gitlab_dir],
  }

  file { "${quill_gitlab_dir}/api-tunnel-known_hosts":
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => "127.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL8IV6XOFkcGWKuvfpbEixC7KPDKpfxPGGownlkEVWzw\n",
    require => File[$quill_gitlab_dir],
  }

  file { "${quill_gitlab_dir}/api-tunnel-ssh.conf":
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("SSH_CONFIG"),
      Host quill-gitlab-api-tunnel
          HostName 127.0.0.1
          Port 22
          User ${nest::user}
          IdentityFile ${quill_gitlab_dir}/api-tunnel-id_ed25519
          IdentitiesOnly yes
          UserKnownHostsFile ${quill_gitlab_dir}/api-tunnel-known_hosts
          StrictHostKeyChecking yes
          BatchMode yes
          PasswordAuthentication no
          KbdInteractiveAuthentication no
          ExitOnForwardFailure yes
          RequestTTY no
      | SSH_CONFIG
    require => File[$quill_gitlab_dir],
  }

  file { "${quill_gitlab_dir}/api":
    ensure  => file,
    mode    => '0700',
    owner   => $nest::user,
    group   => $nest::user,
    source  => 'puppet:///modules/nest/scripts/quill-gitlab-api',
    require => File[$quill_gitlab_dir],
  }

  file { "/home/${nest::user}/.ssh/authorized_keys2":
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => "from=\"127.0.0.1,::1\",command=\"/bin/false\",no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc,permitopen=\"127.0.0.1:80\" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMZuxrY9tUUfC6K6kPWIUiDqyMLJVoTyAQF4nuLo/Q3v quill-gitlab-api-tunnel\n",
  }

  file { "${quill_gitlab_ssh_dir}/id_ed25519":
    ensure    => file,
    mode      => '0600',
    owner     => $nest::user,
    group     => $nest::user,
    content   => $quill_gitlab_ssh_private_key,
    show_diff => false,
    require   => File[$quill_gitlab_ssh_dir],
  }

  file { "${quill_gitlab_ssh_dir}/known_hosts":
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => "[gitlab.puppet]:2222 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIILpJA7qvWaPXnNHqYHDC7rEZjfL8mzRnRYx5YZTF484\n",
    require => File[$quill_gitlab_ssh_dir],
  }

  file { "${quill_gitlab_ssh_dir}/config":
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("SSH_CONFIG"),
      Host gitlab.puppet
          HostName gitlab.puppet
          Port 2222
          User git
          IdentityFile ${quill_gitlab_ssh_dir}/id_ed25519
          IdentitiesOnly yes
          UserKnownHostsFile ${quill_gitlab_ssh_dir}/known_hosts
          StrictHostKeyChecking yes
      | SSH_CONFIG
    require => File[$quill_gitlab_ssh_dir],
  }

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
