class nest::app::hermes::service {
  $install_dir             = $nest::app::hermes::install_dir
  $venv_dir                = "${install_dir}/venv"
  $venv_python             = "${venv_dir}/bin/python"
  $source_dir              = "${install_dir}/src"
  $broker_source_dir            = "${install_dir}/agent-request-broker"
  $pythonpath                   = "${source_dir}:${broker_source_dir}/src"
  $hermes_home_dir              = "/home/${nest::user}/.hermes"
  $systemd_user_dir        = "/home/${nest::user}/.config/systemd/user"
  $systemd_main_pid        = '$MAINPID'

  file { $systemd_user_dir:
    ensure => directory,
    mode   => '0755',
    owner  => $nest::user,
    group  => $nest::user,
  }
  file { "${install_dir}/bin":
    ensure  => directory,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File[$install_dir],
  }

  file { "${install_dir}/bin/manage-hermes-config":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => epp('nest/app/hermes/manage-hermes-config.py.epp'),
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-dashboard":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => epp('nest/app/hermes/dashboard.sh.epp', {
      'venv_python' => $venv_python,
    }),
    require => [
      File["${install_dir}/bin"],
      Exec['install_hermes_agent'],
    ],
  }

  file { "${install_dir}/bin/hermes-systemd-user-refresh":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/app/hermes/hermes-systemd-user-refresh',
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-share-codex-auth":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/app/hermes/share-codex-auth.py',
    require => File["${install_dir}/bin"],
  }

  $agent_request_review_commands = [
    'agent-request-approve',
    'agent-request-propose',
    'agent-request-maintain',
    'agent-request-supersede',
    'agent-request-cancel',
    'agent-request-deny',
  ]

  $agent_request_worktree_cleanup_commands = [
    'agent-request-cleanup-terminal-resources',
  ]

  $agent_request_archive_commands = [
    'agent-request-archive-completed',
  ]

  $agent_request_command_wrappers = $agent_request_review_commands + $agent_request_worktree_cleanup_commands + $agent_request_archive_commands

  $agent_request_command_wrappers.each |String $agent_request_command| {
    file { "${install_dir}/bin/${agent_request_command}":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => epp('nest/app/hermes/agent-request-command.sh.epp', {
        'venv_dir'          => $venv_dir,
        'venv_python'       => $venv_python,
        'source_dir'        => $source_dir,
        'broker_source_dir' => $broker_source_dir,
        'hermes_home_dir'   => $hermes_home_dir,
        'pythonpath'        => $pythonpath,
        'command'           => $agent_request_command,
      }),
      require => [
        File["${install_dir}/bin"],
        Exec['install_hermes_agent_request_broker'],
      ],
    }
  }

  systemd::manage_unit { 'hermes-gateway@.service':
    ensure        => present,
    path          => $systemd_user_dir,
    owner         => $nest::user,
    group         => $nest::user,
    mode          => '0644',
    daemon_reload => false,
    unit_entry    => {
      'Description'           => 'Hermes Agent Gateway (%i)',
      'After'                 => 'network-online.target',
      'Wants'                 => 'network-online.target',
      'StartLimitIntervalSec' => '0',
    },
    service_entry => {
      'Type'                   => 'simple',
      'EnvironmentFile'        => "-${hermes_home_dir}/profiles/%i/systemd.env",
      'ExecStart'              => "${venv_python} -m hermes_cli.main --profile %i gateway run --replace",
      'WorkingDirectory'       => "/home/${nest::user}",
      'Environment'            => [
        "PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "VIRTUAL_ENV=${venv_dir}",
        "PYTHONPATH=${pythonpath}",
        "HERMES_HOME=${hermes_home_dir}",
        'SSL_CERT_FILE=',
        'SSL_CERT_DIR=/etc/ssl/certs',
      ],
      'Restart'                => 'always',
      'RestartSec'             => '5',
      'RestartForceExitStatus' => '75',
      'KillMode'               => 'mixed',
      'KillSignal'             => 'SIGTERM',
      'ExecReload'             => "/bin/kill -USR1 ${systemd_main_pid}",
      'TimeoutStopSec'         => '210',
      'StandardOutput'         => 'journal',
      'StandardError'          => 'journal',
    },
    install_entry => {
      'WantedBy' => 'default.target',
    },
    require       => Exec['install_hermes_agent'],
    notify        => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
  }


  systemd::manage_unit { 'hermes-dashboard@.service':
    ensure        => present,
    path          => $systemd_user_dir,
    owner         => $nest::user,
    group         => $nest::user,
    mode          => '0644',
    daemon_reload => false,
    unit_entry    => {
      'Description'           => 'Hermes Agent Dashboard (%i)',
      'After'                 => 'network-online.target',
      'Wants'                 => 'network-online.target',
      'StartLimitIntervalSec' => '0',
    },
    service_entry => {
      'Type'             => 'simple',
      'EnvironmentFile'  => "${hermes_home_dir}/profiles/%i/systemd.env",
      'ExecStart'        => "${install_dir}/bin/hermes-dashboard %i",
      'WorkingDirectory' => "/home/${nest::user}",
      'Environment'      => [
        "PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "VIRTUAL_ENV=${venv_dir}",
        "PYTHONPATH=${pythonpath}",
        "HERMES_HOME=${hermes_home_dir}",
        'HERMES_DASHBOARD_TUI=1',
        "HERMES_TUI_DIR=${source_dir}/ui-tui",
        'SSL_CERT_FILE=',
        'SSL_CERT_DIR=/etc/ssl/certs',
      ],
      'Restart'          => 'always',
      'RestartSec'       => '5',
      'StandardOutput'   => 'journal',
      'StandardError'    => 'journal',
    },
    install_entry => {
      'WantedBy' => 'default.target',
    },
    require       => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_pty_deps'],
      Exec['build_hermes_tui'],
    ],
    notify        => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
  }




  systemd::daemon_reload { 'hermes-systemd-user-daemon-reload':
    user => $nest::user,
  }

  loginctl_user { $nest::user:
    linger => enabled,
  }
}
