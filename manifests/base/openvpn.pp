class nest::base::openvpn {
  case $facts['os']['family'] {
    'Gentoo': {
      $openvpn_package_name = 'net-vpn/openvpn'
      $openvpn_package_opts = undef

      File {
        owner => 'root',
        group => 'root',
      }

      nest::lib::package_use { $openvpn_package_name:
        use     => 'dco',
        require => Class['nest::base::kernel'],
      }

      if $nest::kernel_config['CONFIG_OVPN'] {
        $ovpn_module = 'ovpn'

        file_line { 'package.provided-ovpn-dco':
          path   => '/etc/portage/profile/package.provided',
          line   => 'net-vpn/ovpn-dco-9999',
          before => Package[$openvpn_package_name],
        }

        # Use latest sources for upstream kernel module support
        package_accept_keywords { $openvpn_package_name:
          accept_keywords => '**',
          before          => Package[$openvpn_package_name],
        }
      } else {
        $ovpn_module = 'ovpn-dco-v2'
      }

      file { [
        '/etc/systemd/system/openvpn-client@.service.d',
        '/etc/systemd/system/openvpn-server@.service.d',
      ]:
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }
      ->
      file { [
        '/etc/systemd/system/openvpn-client@.service.d/10-kmod.conf',
        '/etc/systemd/system/openvpn-server@.service.d/10-kmod.conf',
      ]:
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => epp('nest/openvpn/kmod.conf.epp', { 'ovpn_module' => $ovpn_module }),
        notify  => Nest::Lib::Systemd_reload['openvpn'],
      }

      file { '/etc/systemd/system/openvpn-client@.service.d/20-bird.conf':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => epp('nest/openvpn/bird.conf.epp'),
        notify  => Nest::Lib::Systemd_reload['openvpn'],
      }

      if $nest::router {
        contain 'nest::lib::router'

        $mode = 'server'
        $openvpn_config = epp('nest/openvpn/config.epp', { 'server' => udp })

        exec { 'openvpn-create-dh-parameters':
          command => '/usr/bin/openssl dhparam -out /etc/openvpn/dh4096.pem 4096',
          creates => '/etc/openvpn/dh4096.pem',
          timeout => 0,
          require => Package['net-vpn/openvpn'],
          before  => Service["openvpn-${mode}@nest"],
        }

        file {
          default:
            require => Package['net-vpn/openvpn'],
            before  => Service["openvpn-${mode}@nest"],
          ;
          '/etc/openvpn/.manage-hosts.sh':
            mode   => '0755',
            source => 'puppet:///modules/nest/openvpn/manage-hosts.sh',
          ;
          [
            '/etc/openvpn/client-connect.sh',
            '/etc/openvpn/client-disconnect.sh',
          ]:
            ensure => link,
            target => '.manage-hosts.sh',
          ;
        }

        Service <| title == 'dnsmasq' |> {
          require +> Service["openvpn-${mode}@nest"],
        }

        nest::lib::external_service { 'openvpn': }

        #
        # Manage TCP service
        #
        file { '/etc/openvpn/server/nest-tcp.conf':
          mode    => '0644',
          content => epp('nest/openvpn/config.epp', { 'server' => tcp }),
          require => Package[$openvpn_package_name],
        }
        ~>
        service { 'openvpn-server@nest-tcp':
          enable => true,
        }

        # Override built-in openvpn service to add TCP port
        firewalld_custom_service { 'openvpn':
          ensure => present,
          ports  => [
            { 'port' => '1194', 'protocol' => 'udp' },
            { 'port' => '1194', 'protocol' => 'tcp' },
          ],
          # autobefore Firewalld_service['openvpn']
        }

        # Disable client service that may have been enabled in early build stage
        service { 'openvpn-client@nest':
          enable => false,
        }
      } else {
        $mode = 'client'
        $openvpn_config = epp('nest/openvpn/config.epp')
      }

      nest::lib::systemd_reload { 'openvpn': }

      $openvpn_config_file      = "/etc/openvpn/${mode}/nest.conf"
      $openvpn_service_name     = "openvpn-${mode}@nest"
      $openvpn_service_provider = undef

      file { "/etc/openvpn/${mode}":
        ensure  => directory,
        mode    => '0755',
        require => Package[$openvpn_package_name],
      }
    }

    'Darwin': {
      $openvpn_package_name     = 'openvpn'
      $openvpn_package_opts     = undef
      $openvpn_config_file      = '/opt/homebrew/etc/openvpn/openvpn.conf'
      $openvpn_config           = epp('nest/openvpn/config.epp')
      $openvpn_service_name     = 'openvpn'
      $openvpn_service_provider = 'homebrew'
    }

    'windows': {
      $openvpn_package_name     = 'openvpn'
      $openvpn_package_opts     = ['--package-parameters', '"', '/Service', '/TapDriver', '"']
      $openvpn_config_file      = 'C:/Program Files/OpenVPN/config-auto/nest.ovpn'
      $openvpn_config           = epp('nest/openvpn/config.epp')
      $openvpn_service_name     = 'OpenVPNService'
      $openvpn_service_provider = undef
    }
  }

  package { $openvpn_package_name:
    ensure          => installed,
    install_options => $openvpn_package_opts,
  }
  ->
  file { $openvpn_config_file:
    mode    => '0644',
    content => $openvpn_config,
  }
  ~>
  service { $openvpn_service_name:
    enable   => $nest::vpn or $nest::router,
    provider => $openvpn_service_provider,
  }
}
