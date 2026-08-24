class nest::app::hermes::service {
  $install_dir             = $nest::app::hermes::install_dir
  $venv_dir                = "${install_dir}/venv"
  $venv_python             = "${venv_dir}/bin/python"
  $source_dir              = "${install_dir}/src"
  $broker_source_dir            = "${install_dir}/agent-request-broker"
  $pythonpath                   = "${source_dir}:${broker_source_dir}/src"
  $hermes_home_dir              = "/home/${nest::user}/.hermes"
  $ca_bundle_file               = $nest::app::hermes::ca_bundle_file
  $systemd_user_dir        = "/home/${nest::user}/.config/systemd/user"
  $systemd_main_pid        = '$MAINPID'
  $gitlab_mr_note_poller_profile  = $nest::app::hermes::gitlab_mr_note_poller_profile
  $gitlab_mr_note_poller_interval = $nest::app::hermes::gitlab_mr_note_poller_interval
  $moving_ticket_interval             = $nest::app::hermes::moving_ticket_interval
  $star_order_refresh_profile     = $nest::app::hermes::star_order_refresh_profile
  $star_order_refresh_interval    = $nest::app::hermes::star_order_refresh_interval
  $patternkit_session_enabled     = $nest::app::hermes::patternkit_session_enabled
  $patternkit_session_token       = $nest::app::hermes::patternkit_session_token

  file { $systemd_user_dir:
    ensure => directory,
    mode   => '0755',
    owner  => $nest::user,
    group  => $nest::user,
  }
  file { "${install_dir}/bin/manage-hermes-config":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => epp('nest/app/hermes/manage-hermes-config.py.epp'),
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-voice-speech-stt":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/app/hermes/voice-speech-stt-command.py',
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-voice-speech-tts":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/app/hermes/voice-speech-tts-command.py',
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

  file { "${install_dir}/bin/star-order-refresh-runner":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/app/hermes/star-order-refresh-runner.py',
    require => File["${install_dir}/bin"],
  }

  $patternkit_session_broker_path = "${install_dir}/bin/patternkit_session_broker.py"
  $patternkit_session_env_path = '/etc/patternkit-session-broker.env'

  if $patternkit_session_enabled {
    $patternkit_session_token_value = $patternkit_session_token ? {
      undef   => fail('Star Pattern Kit session tooling requires patternkit_session_token'),
      default => $patternkit_session_token.unwrap,
    }

    file { $patternkit_session_broker_path:
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      source  => 'puppet:///modules/nest/app/hermes/patternkit_session_broker.py',
      require => File["${install_dir}/bin"],
      notify  => Service['patternkit-session-broker'],
    }

    file { $patternkit_session_env_path:
      ensure    => file,
      mode      => '0600',
      owner     => 'root',
      group     => 'root',
      content   => Sensitive("PATTERNKIT_SESSION_BRIDGE_TOKEN=${patternkit_session_token_value}\n"),
      show_diff => false,
      notify    => Service['patternkit-session-broker'],
    }

    file { '/etc/systemd/system/patternkit-session-broker.service':
      ensure  => file,
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => @("UNIT"),
        [Unit]
        Description=Star Pattern Kit exact-session credential broker
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        User=root
        Group=${nest::user}
        EnvironmentFile=${patternkit_session_env_path}
        RuntimeDirectory=patternkit-session-broker
        RuntimeDirectoryMode=0750
        ExecStart=${venv_python} ${patternkit_session_broker_path}
        ExecStartPost=/usr/bin/timeout 30 /bin/sh -c 'until /usr/bin/test -S /run/patternkit-session-broker/patternkit-session.sock; do /bin/sleep 0.1; done'
        Restart=on-failure
        RestartSec=5
        NoNewPrivileges=true
        PrivateTmp=true
        ProtectHome=read-only
        ProtectSystem=strict
        ReadWritePaths=/run/patternkit-session-broker

        [Install]
        WantedBy=multi-user.target
        | UNIT
      require => File[$patternkit_session_env_path],
      notify  => Exec['patternkit-session-systemd-reload'],
    }

    exec { 'patternkit-session-systemd-reload':
      command     => '/bin/systemctl daemon-reload',
      refreshonly => true,
    }

    service { 'patternkit-session-broker':
      ensure    => running,
      enable    => true,
      subscribe => File['/etc/systemd/system/patternkit-session-broker.service'],
      require   => [
        Exec['patternkit-session-systemd-reload'],
        File[$patternkit_session_broker_path],
        File[$patternkit_session_env_path],
      ],
    }
  } else {
    service { 'patternkit-session-broker':
      ensure => stopped,
      enable => false,
    }

    file { [
      $patternkit_session_broker_path,
      $patternkit_session_env_path,
      '/etc/systemd/system/patternkit-session-broker.service',
    ]:
      ensure => absent,
      notify => Exec['patternkit-session-systemd-reload'],
    }

    exec { 'patternkit-session-systemd-reload':
      command     => '/bin/systemctl daemon-reload',
      refreshonly => true,
    }
  }

  file { [
    "${install_dir}/bin/hermes-share-codex-auth",
    "${install_dir}/bin/hermes-codex-auth",
  ]:
    ensure  => absent,
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-manage-codex-pool":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/app/hermes/manage-codex-pool.py',
    require => File["${install_dir}/bin"],
  }

  $agent_request_review_commands = [
    'agent-request-approve',
    'agent-request-propose',
    'agent-request-accept-review',
    'agent-request-maintain',
    'agent-request-supersede',
    'agent-request-cancel',
    'agent-request-deny',
  ]

  $agent_request_diagnostic_commands = [
    'agent-request-doctor',
    'agent-request-poll-gitlab-mr-notes',
    'agent-request-reconcile-moving-tickets',
    'agent-request-reconcile-gitlab-mr-note',
    'agent-request-tts-cadence-evaluate',
  ]

  $agent_request_worktree_cleanup_commands = [
    'agent-request-cleanup-terminal-resources',
  ]

  $agent_request_archive_commands = [
    'agent-request-archive-completed',
  ]

  $agent_request_command_wrappers = $agent_request_review_commands + $agent_request_diagnostic_commands + $agent_request_worktree_cleanup_commands + $agent_request_archive_commands

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

  if $nest::app::hermes::gitlab_mr_note_poller_enabled {
    file { "${systemd_user_dir}/hermes-agent-request-gitlab-mr-notes.service":
      ensure  => file,
      mode    => '0644',
      owner   => $nest::user,
      group   => $nest::user,
      content => @("UNIT"),
        [Unit]
        Description=Hermes Agent Request GitLab MR note poller
        Documentation=file:/opt/hermes-agent/agent-request-broker/docs/gitlab-mr-note-reconciliation.md
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=oneshot
        EnvironmentFile=-${hermes_home_dir}/profiles/${gitlab_mr_note_poller_profile}/systemd.env
        Environment=HERMES_HOME=${hermes_home_dir}
        Environment=AGENT_REQUEST_KANBAN_BOARD=${nest::app::hermes::agent_request_kanban_board}
        Environment=PYTHONPATH=${pythonpath}
        Environment=SSL_CERT_FILE=${ca_bundle_file}
        Environment=REQUESTS_CA_BUNDLE=${ca_bundle_file}
        Environment=CURL_CA_BUNDLE=${ca_bundle_file}
        Environment=SSL_CERT_DIR=/etc/ssl/certs
        ExecStart=${venv_python} -m agent_request_broker.gitlab_mr_note_poller --board ${nest::app::hermes::agent_request_kanban_board} --json
        WorkingDirectory=/home/${nest::user}
        StandardOutput=journal
        StandardError=journal
        | UNIT
      require => [
        File[$systemd_user_dir],
        Exec['install_hermes_agent_request_broker'],
      ],
      notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/hermes-agent-request-gitlab-mr-notes.timer":
      ensure  => file,
      mode    => '0644',
      owner   => $nest::user,
      group   => $nest::user,
      content => @("UNIT"),
        [Unit]
        Description=Poll GitLab MR notes for Hermes Agent Request steering
        Documentation=file:/opt/hermes-agent/agent-request-broker/docs/gitlab-mr-note-reconciliation.md

        [Timer]
        OnBootSec=2min
        OnUnitActiveSec=${gitlab_mr_note_poller_interval}
        RandomizedDelaySec=15s
        AccuracySec=15s
        Persistent=false

        [Install]
        WantedBy=timers.target
        | UNIT
      require => File["${systemd_user_dir}/hermes-agent-request-gitlab-mr-notes.service"],
      notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    systemd::user_service { 'hermes-agent-request-gitlab-mr-notes':
      ensure  => running,
      enable  => true,
      unit    => 'hermes-agent-request-gitlab-mr-notes.timer',
      user    => $nest::user,
      require => [
        Loginctl_user[$nest::user],
        File["${systemd_user_dir}/hermes-agent-request-gitlab-mr-notes.timer"],
      ],
    }
  } else {
    systemd::user_service { 'hermes-agent-request-gitlab-mr-notes':
      ensure => stopped,
      enable => false,
      unit   => 'hermes-agent-request-gitlab-mr-notes.timer',
      user   => $nest::user,
    }

    file { "${systemd_user_dir}/hermes-agent-request-gitlab-mr-notes.timer":
      ensure => absent,
      owner  => $nest::user,
      group  => $nest::user,
      notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/hermes-agent-request-gitlab-mr-notes.service":
      ensure => absent,
      owner  => $nest::user,
      group  => $nest::user,
      notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }
  }

  if $nest::app::hermes::moving_ticket_enabled {
    file { "${systemd_user_dir}/hermes-agent-request-moving-tickets.service":
      ensure  => file,
      mode    => '0644',
      owner   => $nest::user,
      group   => $nest::user,
      content => @("UNIT"),
        [Unit]
        Description=Reconcile Agent Requests which have lost a moving owner
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=oneshot
        Environment=HERMES_HOME=${hermes_home_dir}
        Environment=AGENT_REQUEST_KANBAN_BOARD=${nest::app::hermes::agent_request_kanban_board}
        ExecStart=${install_dir}/bin/agent-request-reconcile-moving-tickets --board ${nest::app::hermes::agent_request_kanban_board} --apply
        WorkingDirectory=/home/${nest::user}
        StandardOutput=journal
        StandardError=journal
        | UNIT
      require => [
        File[$systemd_user_dir],
        File["${install_dir}/bin/agent-request-reconcile-moving-tickets"],
        Exec['install_hermes_agent_request_broker'],
      ],
      notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/hermes-agent-request-moving-tickets.timer":
      ensure  => file,
      mode    => '0644',
      owner   => $nest::user,
      group   => $nest::user,
      content => @("UNIT"),
        [Unit]
        Description=Watchdog for non-moving Agent Request waits

        [Timer]
        OnBootSec=2min
        OnUnitActiveSec=${moving_ticket_interval}
        RandomizedDelaySec=30s
        Persistent=true
        Unit=hermes-agent-request-moving-tickets.service

        [Install]
        WantedBy=timers.target
        | UNIT
      require => File["${systemd_user_dir}/hermes-agent-request-moving-tickets.service"],
      notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    systemd::user_service { 'hermes-agent-request-moving-tickets':
      ensure  => running,
      enable  => true,
      unit    => 'hermes-agent-request-moving-tickets.timer',
      user    => $nest::user,
      require => [
        Loginctl_user[$nest::user],
        File["${systemd_user_dir}/hermes-agent-request-moving-tickets.timer"],
      ],
    }
  } else {
    systemd::user_service { 'hermes-agent-request-moving-tickets':
      ensure => stopped,
      enable => false,
      unit   => 'hermes-agent-request-moving-tickets.timer',
      user   => $nest::user,
    }

    file { "${systemd_user_dir}/hermes-agent-request-moving-tickets.timer":
      ensure => absent,
      owner  => $nest::user,
      group  => $nest::user,
      notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/hermes-agent-request-moving-tickets.service":
      ensure => absent,
      owner  => $nest::user,
      group  => $nest::user,
      notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }
  }

  if $nest::app::hermes::star_order_refresh_enabled {
    file { "${systemd_user_dir}/hermes-star-order-refresh.service":
      ensure  => file,
      mode    => '0644',
      owner   => $nest::user,
      group   => $nest::user,
      content => @("UNIT"),
        [Unit]
        Description=Star safe shopping-order refresh and material notification pass
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=oneshot
        EnvironmentFile=-${hermes_home_dir}/profiles/${star_order_refresh_profile}/systemd.env
        Environment=HERMES_HOME=${hermes_home_dir}
        Environment=HERMES_PROFILE=${star_order_refresh_profile}
        Environment=PYTHONPATH=${pythonpath}
        Environment=SSL_CERT_FILE=${ca_bundle_file}
        Environment=REQUESTS_CA_BUNDLE=${ca_bundle_file}
        Environment=CURL_CA_BUNDLE=${ca_bundle_file}
        Environment=SSL_CERT_DIR=/etc/ssl/certs
        ExecStart=${venv_python} ${install_dir}/bin/star-order-refresh-runner --json
        WorkingDirectory=/home/${nest::user}
        StandardOutput=journal
        StandardError=journal
        | UNIT
      require => [
        File[$systemd_user_dir],
        File["${install_dir}/bin/star-order-refresh-runner"],
        Exec['install_hermes_agent'],
      ],
      notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/hermes-star-order-refresh.timer":
      ensure  => file,
      mode    => '0644',
      owner   => $nest::user,
      group   => $nest::user,
      content => @("UNIT"),
        [Unit]
        Description=Schedule Star safe shopping-order refreshes

        [Timer]
        OnBootSec=10min
        OnUnitActiveSec=${star_order_refresh_interval}
        RandomizedDelaySec=5min
        AccuracySec=1min
        Persistent=false

        [Install]
        WantedBy=timers.target
        | UNIT
      require => File["${systemd_user_dir}/hermes-star-order-refresh.service"],
      notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    systemd::user_service { 'hermes-star-order-refresh':
      ensure  => running,
      enable  => true,
      unit    => 'hermes-star-order-refresh.timer',
      user    => $nest::user,
      require => [
        Loginctl_user[$nest::user],
        File["${systemd_user_dir}/hermes-star-order-refresh.timer"],
      ],
    }
  } else {
    systemd::user_service { 'hermes-star-order-refresh':
      ensure => stopped,
      enable => false,
      unit   => 'hermes-star-order-refresh.timer',
      user   => $nest::user,
    }

    file { "${systemd_user_dir}/hermes-star-order-refresh.timer":
      ensure => absent,
      owner  => $nest::user,
      group  => $nest::user,
      notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/hermes-star-order-refresh.service":
      ensure => absent,
      owner  => $nest::user,
      group  => $nest::user,
      notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
    }
  }

  systemd::user_service { 'hermes-agent-request-bridge-loop':
    ensure => stopped,
    enable => false,
    unit   => 'hermes-agent-request-bridge-loop.timer',
    user   => $nest::user,
  }

  file { "${systemd_user_dir}/timers.target.wants/hermes-agent-request-bridge-loop.timer":
    ensure => absent,
    notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
  }

  file { "${systemd_user_dir}/hermes-agent-request-bridge-loop.timer":
    ensure => absent,
    owner  => $nest::user,
    group  => $nest::user,
    notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
  }

  file { "${systemd_user_dir}/hermes-agent-request-bridge-loop.service":
    ensure => absent,
    owner  => $nest::user,
    group  => $nest::user,
    notify => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
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
        "SSL_CERT_FILE=${ca_bundle_file}",
        "REQUESTS_CA_BUNDLE=${ca_bundle_file}",
        "CURL_CA_BUNDLE=${ca_bundle_file}",
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
        "SSL_CERT_FILE=${ca_bundle_file}",
        "REQUESTS_CA_BUNDLE=${ca_bundle_file}",
        "CURL_CA_BUNDLE=${ca_bundle_file}",
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
