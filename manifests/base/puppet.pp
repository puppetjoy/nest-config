class nest::base::puppet {
  tag 'profile'

  $puppetcore_gem_source = 'https://rubygems-puppetcore.puppet.com'

  if $nest::router {
    $dns_alt_names = $nest::openvpn_servers.filter |$s| { $s !~ Stdlib::IP::Address }
  } else {
    $dns_alt_names = []
  }

  $fqdn_yaml = {
    'fqdn' => "${trusted['certname']}.nest",
  }.stdlib::to_yaml

  if $nest::puppet_forge_key {
    $puppetcore_env_content = Sensitive(epp('nest/puppet/puppetcore-env.epp', {
      'puppet_forge_key'      => $nest::puppet_forge_key.unwrap,
      'puppetcore_gem_source' => $puppetcore_gem_source,
    }))
  } else {
    $puppetcore_env_content = undef
  }

  case $facts['os']['family'] {
    'Gentoo': {
      $puppetcore_env_path = '/etc/profile.d/puppetcore.sh'

      file { [
        '/etc/puppetlabs',
        '/etc/puppetlabs/facter',
        '/etc/puppetlabs/facter/facts.d',
      ]:
        ensure => 'directory',
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }

      $facter_conf = @(FACTER_CONF)
        global : {
            external-dir : [ "/etc/puppetlabs/facter/facts.d" ]
        }
        | FACTER_CONF

      file { '/etc/puppetlabs/facter/facter.conf':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => $facter_conf,
      }

      file { '/etc/puppetlabs/facter/facts.d/outputs.yaml':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => epp('nest/puppet/outputs.yaml.epp'),
      }

      # My hosts take on the domain name of the network to which they're attached.
      # Provide a stable, canonical value for Puppet.
      file { '/etc/puppetlabs/facter/facts.d/fqdn.yaml':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => $fqdn_yaml,
      }

      if $facts['build'] {
        $puppet_runmode = 'unmanaged'
      } elsif !$nest::puppet {
        $puppet_runmode = 'none'
      } else {
        $puppet_runmode = 'systemd.timer'

        file {
          default:
            mode   => '0644',
            owner  => 'root',
            group  => 'root',
            before => Class['puppet'],
          ;

          '/etc/systemd/system/puppet-run.timer.d':
            ensure => directory,
          ;

          # Avoid running Puppet immediately at boot; just wait for the next run
          '/etc/systemd/system/puppet-run.timer.d/10-nonpersistent.conf':
            content => "[Timer]\nPersistent=false\n",
          ;
        }
      }

      class { 'puppet':
        dns_alt_names        => $dns_alt_names,
        dir                  => '/etc/puppetlabs/puppet',
        codedir              => '/etc/puppetlabs/code',
        ssldir               => '/etc/puppetlabs/puppet/ssl',
        runmode              => $puppet_runmode,
        unavailable_runmodes => ['cron'],
        additional_settings  => {
          'publicdir' => '/var/lib/puppet/public',
        },
      }

      # Override failing systemd reload in build containers
      if $facts['is_container'] {
        Exec <| title == 'systemctl-daemon-reload-puppet' |> {
          noop => true,
        }
      }
    }

    'Darwin': {
      $puppetcore_env_path = '/etc/profile.d/puppetcore.sh'

      $facter_conf = @(FACTER_CONF)
        global : {
            external-dir : [ "/etc/puppetlabs/facter/facts.d" ]
        }
        | FACTER_CONF

      file {
        default:
          mode  => '0644',
          owner => 'root',
          group => 'wheel',
        ;

        ['/etc/puppetlabs/facter', '/etc/puppetlabs/facter/facts.d']:
          ensure => directory,
        ;

        '/etc/puppetlabs/facter/facter.conf':
          content => $facter_conf,
        ;

        '/etc/puppetlabs/facter/facts.d/fqdn.yaml':
          content => $fqdn_yaml,
        ;
      }

      file { '/etc/profile.d':
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'wheel',
      }

      file_line { 'macos-profile-source-profile-d-puppetcore':
        path  => '/etc/profile',
        line  => '[ -r /etc/profile.d/puppetcore.sh ] && . /etc/profile.d/puppetcore.sh',
        match => 'puppetcore\.sh',
      }

      file_line { 'macos-zprofile-source-profile-d-puppetcore':
        path  => '/etc/zprofile',
        line  => '[ -r /etc/profile.d/puppetcore.sh ] && . /etc/profile.d/puppetcore.sh',
        match => 'puppetcore\.sh',
      }

      if $nest::puppet {
        # macOS 26.x can crash the long-lived agent's forked child during DNS resolution.
        # Use the module's cron runmode so each agent run starts in a fresh process.
        $puppet_runmode = 'cron'
      } else {
        $puppet_runmode = 'none'
      }

      homebrew::tap { 'openvoxproject/openvox': }
      ->
      class { 'puppet':
        client_package       => 'openvox8-agent',
        package_provider     => 'homebrew',
        dns_alt_names        => $dns_alt_names,
        runmode              => $puppet_runmode,
        unavailable_runmodes => ['systemd.timer'],
      }
    }

    'windows': {
      $puppetcore_env_path = 'C:/tools/cygwin/etc/profile.d/puppetcore.sh'

      $facter_conf = @(FACTER_CONF)
        global : {
            external-dir : [ "C:/ProgramData/PuppetLabs/facter/facts.d" ]
        }
        | FACTER_CONF

      file {
        default:
          mode  => '0644',
          owner => 'Administrators',
          group => 'None',
        ;

        'C:/ProgramData/PuppetLabs/facter/etc':
          ensure => directory,
        ;

        'C:/ProgramData/PuppetLabs/facter/etc/facter.conf':
          content => $facter_conf,
        ;

        'C:/ProgramData/PuppetLabs/facter/facts.d/fqdn.yaml':
          content => $fqdn_yaml,
        ;
      }

      file { 'C:/ProgramData/PuppetLabs/facter/facts.d/outputs.yaml':
        mode    => '0644',
        owner   => 'Administrators',
        group   => 'None',
        content => epp('nest/puppet/outputs.yaml.epp'),
      }

      if $nest::puppet {
        $puppet_runmode = 'service'
      } else {
        $puppet_runmode = 'none'
      }

      class { 'puppet':
        dns_alt_names => $dns_alt_names,
        runmode       => $puppet_runmode,
      }
    }
  }

  if $puppetcore_env_content {
    file { $puppetcore_env_path:
      ensure    => file,
      mode      => '0644',
      show_diff => false,
      content   => $puppetcore_env_content,
    }
  } else {
    file { $puppetcore_env_path:
      ensure => absent,
    }
  }
}
