class nest::app::hermes (
  Optional[String[1]]            $version      = undef,
  Stdlib::Absolutepath           $install_dir  = '/opt/hermes-agent',
  String[1]                      $gitlab_url   = 'https://gitlab.joyfullee.me',
  Optional[Sensitive[String[1]]] $gitlab_token = undef,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      $venv_dir                   = "${install_dir}/venv"
      $venv_python                = "${venv_dir}/bin/python"
      $venv_pip                   = "${venv_dir}/bin/pip"
      $hermes_config_dir          = "/home/${nest::user}/.config/hermes"
      $hermes_gitlab_env_path     = "${hermes_config_dir}/gitlab.env"
      $systemd_user_dir           = "/home/${nest::user}/.config/systemd/user"
      $hermes_gateway_dropin_dir  = "${systemd_user_dir}/hermes-gateway.service.d"
      $hermes_environment_unit    = 'hermes-environment.service'
      $package_spec               = $version ? {
        undef   => 'hermes-agent',
        default => "hermes-agent==${version}",
      }

      $install_unless = $version ? {
        undef   => "${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\"",
        default => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('hermes-agent') == '${version}' else 1)\"",
      }

      nest::lib::package { 'dev-python/virtualenv':
        ensure => present,
      }

      ensure_resource('nest::lib::package', 'sys-apps/ripgrep', {
        'ensure' => 'present',
      })

      file { $install_dir:
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }
      ->
      exec { 'create_hermes_venv':
        command => "/usr/bin/python3 -m virtualenv ${venv_dir}",
        creates => $venv_python,
        require => Nest::Lib::Package['dev-python/virtualenv'],
      }
      ->
      exec { 'install_hermes_agent':
        command     => "${venv_pip} install ${package_spec}",
        unless      => $install_unless,
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      }
      ->
      file { '/usr/local/bin/hermes':
        ensure => link,
        target => "${venv_dir}/bin/hermes",
      }

      exec { 'install_hermes_telegram_deps':
        command     => "${venv_pip} install 'python-telegram-bot[webhooks]==22.6'",
        unless      => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('python-telegram-bot') == '22.6' else 1)\"",
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
        require     => Exec['install_hermes_agent'],
      }

      nest::lib::package { 'media-video/ffmpeg':
        ensure => present,
      }

      if $facts['profile']['architecture'] == 'amd64' {
        include 'nodejs'

        nest::lib::package_use { 'media-libs/freetype':
          use => ['harfbuzz'],
        }

        nest::lib::package { 'www-client/google-chrome':
          ensure  => present,
          require => Nest::Lib::Package_use['media-libs/freetype'],
        }

        file { '/usr/local/bin/google-chrome':
          ensure  => link,
          target  => '/usr/bin/google-chrome-stable',
          require => Nest::Lib::Package['www-client/google-chrome'],
        }

        exec { 'install_hermes_agent_browser':
          command     => "${nodejs::npm_path} install --global agent-browser@latest",
          unless      => "${nodejs::npm_path} list --global agent-browser --depth=0 >/dev/null 2>&1 && ${nodejs::npm_path} outdated --global agent-browser --depth=0 >/dev/null 2>&1",
          environment => ['HOME=/root'],
          require     => Class['nodejs'],
        }
      }

      if $gitlab_token {
        $gitlab_env_content = Sensitive(epp('nest/hermes/gitlab.env.epp', {
          'gitlab_url'   => $gitlab_url,
          'gitlab_token' => $gitlab_token.unwrap,
        }))

        file { $hermes_config_dir:
          ensure => directory,
          mode   => '0700',
          owner  => $nest::user,
          group  => $nest::user,
        }
        ->
        file { $hermes_gitlab_env_path:
          ensure    => file,
          mode      => '0600',
          owner     => $nest::user,
          group     => $nest::user,
          show_diff => false,
          content   => $gitlab_env_content,
        }
      } else {
        file { $hermes_gitlab_env_path:
          ensure => absent,
        }
      }

      file { $systemd_user_dir:
        ensure => directory,
        mode   => '0755',
        owner  => $nest::user,
        group  => $nest::user,
      }
      ->
      file { "${systemd_user_dir}/${hermes_environment_unit}":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => @("UNIT"),
          [Unit]
          Description=Import shell environment for Hermes Agent Gateway

          [Service]
          Type=oneshot
          ExecStart=/home/${nest::user}/bin/reset-systemd-environment
          | UNIT
      }

      file { $hermes_gateway_dropin_dir:
        ensure => directory,
        mode   => '0755',
        owner  => $nest::user,
        group  => $nest::user,
      }
      ->
      file { "${hermes_gateway_dropin_dir}/10-shell-environment.conf":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => "[Unit]\nRequires=${hermes_environment_unit}\nAfter=${hermes_environment_unit}\n",
      }
      ->
      file { "${hermes_gateway_dropin_dir}/10-ssh-agent.conf":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => "[Service]\nEnvironment=SSH_AUTH_SOCK=%t/ssh-agent.socket\n",
      }

      if $gitlab_token {
        file { "${hermes_gateway_dropin_dir}/20-gitlab-env.conf":
          ensure  => file,
          mode    => '0644',
          owner   => $nest::user,
          group   => $nest::user,
          content => "[Service]\nEnvironmentFile=${hermes_gitlab_env_path}\n",
          require => File[$hermes_gitlab_env_path],
        }
      } else {
        file { "${hermes_gateway_dropin_dir}/20-gitlab-env.conf":
          ensure => absent,
        }
      }

      File["${systemd_user_dir}/${hermes_environment_unit}"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/20-gitlab-env.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      exec { 'hermes-gateway-systemd-user-daemon-reload':
        command     => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"',
        user        => $nest::user,
        refreshonly => true,
      }
    }
  }
}
