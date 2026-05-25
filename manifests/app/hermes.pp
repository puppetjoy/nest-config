class nest::app::hermes (
  Optional[String[1]]  $version     = undef,
  Stdlib::Absolutepath $install_dir = '/opt/hermes-agent',
) {
  case $facts['os']['family'] {
    'Gentoo': {
      $venv_dir                   = "${install_dir}/venv"
      $venv_python                = "${venv_dir}/bin/python"
      $venv_pip                   = "${venv_dir}/bin/pip"
      $hermes_gateway_dropin_dir  = "/home/${nest::user}/.config/systemd/user/hermes-gateway.service.d"
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

        exec { 'install_hermes_agent_browser':
          command     => "${nodejs::npm_path} install --global agent-browser@latest",
          unless      => "${nodejs::npm_path} list --global agent-browser --depth=0 >/dev/null 2>&1 && ${nodejs::npm_path} outdated --global agent-browser --depth=0 >/dev/null 2>&1",
          environment => ['HOME=/root'],
          require     => Class['nodejs'],
        }
      }

      file { $hermes_gateway_dropin_dir:
        ensure => directory,
        mode   => '0755',
        owner  => $nest::user,
        group  => $nest::user,
      }
      ->
      file { "${hermes_gateway_dropin_dir}/10-ssh-agent.conf":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => "[Service]\nEnvironment=SSH_AUTH_SOCK=%t/ssh-agent.socket\n",
      }
      ~>
      exec { 'hermes-gateway-systemd-user-daemon-reload':
        command     => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"',
        user        => $nest::user,
        refreshonly => true,
      }
    }
  }
}
