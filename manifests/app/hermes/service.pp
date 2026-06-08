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
  file { "${systemd_user_dir}/hermes-environment.service":
    ensure => absent,
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
    content => @("PYTHON"),
      #!/usr/bin/env python3
      import copy
      import sys
      from pathlib import Path

      import yaml


      def load_yaml(path):
          p = Path(path)
          if not p.exists():
              return {}
          with p.open() as fh:
              return yaml.safe_load(fh) or {}


      def deep_merge(base, override):
          result = copy.deepcopy(base)
          for key, value in override.items():
              if isinstance(result.get(key), dict) and isinstance(value, dict):
                  result[key] = deep_merge(result[key], value)
              else:
                  result[key] = copy.deepcopy(value)
          return result


      def dump_yaml(data):
          return yaml.safe_dump(data, default_flow_style=False, sort_keys=True)


      def main():
          if len(sys.argv) != 4 or sys.argv[1] not in {'check', 'apply'}:
              print('usage: manage-hermes-config check|apply CONFIG MANAGED', file=sys.stderr)
              return 2
          mode, config_path, managed_path = sys.argv[1:]
          current = load_yaml(config_path)
          managed = load_yaml(managed_path)
          desired = deep_merge(current, managed)
          current_text = dump_yaml(current)
          desired_text = dump_yaml(desired)
          if mode == 'check':
              return 0 if current_text == desired_text else 1
          if current_text != desired_text:
              Path(config_path).write_text(desired_text)
          return 0


      if __name__ == '__main__':
          raise SystemExit(main())
      | PYTHON
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-dashboard":
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => [
      '#!/bin/sh',
      'set -eu',
      ["exec ${venv_python} -m hermes_cli.main --profile ", '"$1"', ' dashboard --host "${HERMES_DASHBOARD_BIND_HOST}" --port "${HERMES_DASHBOARD_PORT}" --no-open --skip-build --insecure'].join(''),
      '',
    ].join("\n"),
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

  $absent_agent_request_commands = [
    'agent-request-accept-review',
  ]

  $agent_request_worktree_cleanup_commands = [
    'agent-request-cleanup-terminal-resources',
  ]

  $agent_request_archive_commands = [
    'agent-request-archive-completed',
  ]

  $agent_request_review_commands.each |String $agent_request_command| {
    file { "${install_dir}/bin/${agent_request_command}":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => [
        '#!/bin/sh',
        'set -eu',
        "export PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "export VIRTUAL_ENV=${venv_dir}",
        "export HERMES_SRC=${source_dir}",
        "export HERMES_HOME=${hermes_home_dir}",
        "export PYTHONPATH=${pythonpath}",
        ["exec ${venv_python} ${broker_source_dir}/bin/${agent_request_command} ", '"$@"'].join(''),
        '',
      ].join("\n"),
      require => [
        File["${install_dir}/bin"],
        Exec['install_hermes_agent_request_broker'],
      ],
    }
  }

  $agent_request_worktree_cleanup_commands.each |String $agent_request_command| {
    file { "${install_dir}/bin/${agent_request_command}":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => [
        '#!/bin/sh',
        'set -eu',
        "export PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "export VIRTUAL_ENV=${venv_dir}",
        "export HERMES_SRC=${source_dir}",
        "export HERMES_HOME=${hermes_home_dir}",
        "export PYTHONPATH=${pythonpath}",
        ["exec ${venv_python} ${broker_source_dir}/bin/${agent_request_command} ", '"$@"'].join(''),
        '',
      ].join("\n"),
      require => [
        File["${install_dir}/bin"],
        Exec['install_hermes_agent_request_broker'],
      ],
    }
  }

  $agent_request_archive_commands.each |String $agent_request_command| {
    file { "${install_dir}/bin/${agent_request_command}":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => [
        '#!/bin/sh',
        'set -eu',
        "export PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "export VIRTUAL_ENV=${venv_dir}",
        "export HERMES_SRC=${source_dir}",
        "export HERMES_HOME=${hermes_home_dir}",
        "export PYTHONPATH=${pythonpath}",
        ["exec ${venv_python} ${broker_source_dir}/bin/${agent_request_command} ", '"$@"'].join(''),
        '',
      ].join("\n"),
      require => [
        File["${install_dir}/bin"],
        Exec['install_hermes_agent_request_broker'],
      ],
    }
  }

  $absent_agent_request_commands.each |String $absent_agent_request_command| {
    file { "${install_dir}/bin/${absent_agent_request_command}":
      ensure => absent,
    }
  }

  [
    'agent-request-watch',
    'agent-request-response-watch',
    'agent-request-peer-watch',
    'agent-request-review-watch',
  ].each |String $legacy_agent_request_command| {
    file { "${install_dir}/bin/${legacy_agent_request_command}":
      ensure => absent,
    }
  }

  file { "${systemd_user_dir}/hermes-gateway@.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Hermes Agent Gateway (%i)
      After=network-online.target
      Wants=network-online.target
      StartLimitIntervalSec=0

      [Service]
      Type=simple
      EnvironmentFile=-${hermes_home_dir}/profiles/%i/systemd.env
      ExecStart=${venv_python} -m hermes_cli.main --profile %i gateway run --replace
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="PYTHONPATH=${pythonpath}"
      Environment="HERMES_HOME=${hermes_home_dir}"
      Environment="SSL_CERT_FILE="
      Environment="SSL_CERT_DIR=/etc/ssl/certs"
      Restart=always
      RestartSec=5
      RestartForceExitStatus=75
      KillMode=mixed
      KillSignal=SIGTERM
      ExecReload=/bin/kill -USR1 ${systemd_main_pid}
      TimeoutStopSec=210
      StandardOutput=journal
      StandardError=journal

      [Install]
      WantedBy=default.target
      | UNIT
    require => Exec['install_hermes_agent'],
  }

  file { "${systemd_user_dir}/hermes-dashboard@.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Hermes Agent Dashboard (%i)
      After=network-online.target
      Wants=network-online.target
      StartLimitIntervalSec=0

      [Service]
      Type=simple
      EnvironmentFile=${hermes_home_dir}/profiles/%i/systemd.env
      ExecStart=${install_dir}/bin/hermes-dashboard %i
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="PYTHONPATH=${pythonpath}"
      Environment="HERMES_HOME=${hermes_home_dir}"
      Environment="HERMES_DASHBOARD_TUI=1"
      Environment="HERMES_TUI_DIR=${source_dir}/ui-tui"
      Environment="SSL_CERT_FILE="
      Environment="SSL_CERT_DIR=/etc/ssl/certs"
      Restart=always
      RestartSec=5
      StandardOutput=journal
      StandardError=journal

      [Install]
      WantedBy=default.target
      | UNIT
    require => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_pty_deps'],
      Exec['build_hermes_tui'],
    ],
  }

  $legacy_agent_request_units = [
    'hermes-agent-request-watch.service',
    'hermes-agent-request-watch.timer',
    'hermes-agent-request-response-watch-talon.service',
    'hermes-agent-request-response-watch-talon.timer',
    'hermes-agent-request-response-watch-star.service',
    'hermes-agent-request-response-watch-star.timer',
    'hermes-agent-request-peer-watch-talon.service',
    'hermes-agent-request-peer-watch-talon.timer',
    'hermes-agent-request-peer-watch-star.service',
    'hermes-agent-request-peer-watch-star.timer',
    'hermes-agent-request-review-watch-talon.service',
    'hermes-agent-request-review-watch-talon.timer',
  ]

  exec { 'disable_legacy_hermes_agent_request_units':
    command => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user disable --now ${legacy_agent_request_units.join(' ')} || true'",
    unless  => "/bin/sh -c '! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user list-unit-files --no-legend \"hermes-agent-request*\" | /bin/grep -q .'",
    user    => $nest::user,
    require => File[$systemd_user_dir],
  }

  $legacy_agent_request_units.each |String $legacy_agent_request_unit| {
    file { "${systemd_user_dir}/${legacy_agent_request_unit}":
      ensure => absent,
      notify => Exec['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/default.target.wants/${legacy_agent_request_unit}":
      ensure => absent,
      notify => Exec['hermes-systemd-user-daemon-reload'],
    }

    file { "${systemd_user_dir}/timers.target.wants/${legacy_agent_request_unit}":
      ensure => absent,
      notify => Exec['hermes-systemd-user-daemon-reload'],
    }
  }

  file { "${systemd_user_dir}/hermes-gateway.service":
    ensure => absent,
  }

  file { "${systemd_user_dir}/hermes-dashboard.service":
    ensure => absent,
  }

  file { "${systemd_user_dir}/default.target.wants/hermes-gateway.service":
    ensure => absent,
  }

  file { "${systemd_user_dir}/default.target.wants/hermes-dashboard.service":
    ensure => absent,
  }

  file { "${systemd_user_dir}/hermes-gateway.service.d":
    ensure  => absent,
    recurse => true,
    force   => true,
  }

  file { "${systemd_user_dir}/hermes-dashboard.service.d":
    ensure  => absent,
    recurse => true,
    force   => true,
  }

  File["${systemd_user_dir}/hermes-environment.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-gateway@.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-dashboard@.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-gateway.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-dashboard.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  exec { 'hermes-systemd-user-daemon-reload':
    command     => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"',
    user        => $nest::user,
    refreshonly => true,
  }

  exec { 'enable_hermes_gateway_linger':
    command => sprintf('/usr/bin/loginctl enable-linger %s', $nest::user),
    unless  => sprintf('/usr/bin/loginctl show-user %s -p Linger --value | /bin/grep -qx yes', $nest::user),
  }
}
