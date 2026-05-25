class nest::app::hermes (
  Optional[String[1]]  $version         = undef,
  Boolean              $ffmpeg          = false,
  Boolean              $browser         = false,
  Boolean              $gateway_service = false,
  Stdlib::Absolutepath $install_dir     = '/opt/hermes-agent',
) {
  case $facts['os']['family'] {
    'Gentoo': {
      $venv_dir     = "${install_dir}/venv"
      $venv_python  = "${venv_dir}/bin/python"
      $venv_pip     = "${venv_dir}/bin/pip"
      $package_spec = $version ? {
        undef   => 'hermes-agent',
        default => "hermes-agent==${version}",
      }

      $install_unless = $version ? {
        undef   => "${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\"",
        default => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('hermes-agent') == '${version}' else 1)\"",
      }

      nest::lib::package { [
        'dev-python/virtualenv',
        'sys-apps/ripgrep',
      ]:
        ensure => present,
      }

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

      if $ffmpeg {
        nest::lib::package { 'media-video/ffmpeg':
          ensure => present,
        }
      }

      if $browser {
        include 'nodejs'

        $browser_dir = "${install_dir}/browser"

        file { $browser_dir:
          ensure => directory,
          mode   => '0755',
          owner  => 'root',
          group  => 'root',
        }
        ->
        exec { 'npm_install_hermes_browser':
          command     => "${nodejs::npm_path} install agent-browser@^0.26.0 @askjo/camofox-browser@^1.5.2",
          unless      => "${nodejs::npm_path} ls agent-browser @askjo/camofox-browser --depth=0 >/dev/null 2>&1",
          cwd         => $browser_dir,
          environment => ['HOME=/root'],
          require     => Class['nodejs'],
        }
        ->
        file { '/usr/local/bin/agent-browser':
          ensure => link,
          target => "${browser_dir}/node_modules/.bin/agent-browser",
        }
      }

      if $gateway_service {
        $home_dir          = "/home/${nest::user}"
        $user_systemd_dir  = "${home_dir}/.config/systemd/user"
        $restart_exit_code = 75
        $main_pid          = '$MAINPID'

        file { [
          "${home_dir}/.config",
          "${home_dir}/.config/systemd",
          $user_systemd_dir,
          "${user_systemd_dir}/default.target.wants",
        ]:
          ensure => directory,
          mode   => '0755',
          owner  => $nest::user,
          group  => $nest::user,
        }
        ->
        file { "${user_systemd_dir}/hermes-gateway.service":
          ensure  => file,
          mode    => '0644',
          owner   => $nest::user,
          group   => $nest::user,
          content => @("UNIT"/L),
            [Unit]
            Description=Hermes Agent Gateway - Messaging Platform Integration
            After=network-online.target
            Wants=network-online.target
            StartLimitIntervalSec=0

            [Service]
            Type=simple
            ExecStart=${venv_python} -m hermes_cli.main gateway run --replace
            WorkingDirectory=${install_dir}
            Environment="PATH=${venv_dir}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            Environment="VIRTUAL_ENV=${venv_dir}"
            Environment="HERMES_HOME=${home_dir}/.hermes"
            Restart=always
            RestartSec=5
            RestartMaxDelaySec=300
            RestartSteps=5
            RestartForceExitStatus=${restart_exit_code}
            KillMode=mixed
            KillSignal=SIGTERM
            ExecReload=/bin/kill -USR1 ${main_pid}
            TimeoutStopSec=90
            StandardOutput=journal
            StandardError=journal

            [Install]
            WantedBy=default.target
            | UNIT
        }
        ->
        file { "${user_systemd_dir}/default.target.wants/hermes-gateway.service":
          ensure => link,
          owner  => $nest::user,
          group  => $nest::user,
          target => '../hermes-gateway.service',
        }
      }
    }
  }
}
