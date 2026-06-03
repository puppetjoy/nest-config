class nest::app::hermes::service {
  $install_dir             = $nest::app::hermes::install_dir
  $venv_dir                = "${install_dir}/venv"
  $venv_python             = "${venv_dir}/bin/python"
  $source_dir              = "${install_dir}/src"
  $broker_source_dir       = "${install_dir}/agent-request-broker"
  $pythonpath              = "${source_dir}:${broker_source_dir}/src"
  $hermes_home_dir         = "/home/${nest::user}/.hermes"
  $systemd_user_dir        = "/home/${nest::user}/.config/systemd/user"
  $hermes_environment_unit = 'hermes-environment.service'

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
      ["exec ${venv_python} -m hermes_cli.main --profile ", '"$1"', ' dashboard --host "${HERMES_DASHBOARD_BIND_HOST}" --port "${HERMES_DASHBOARD_PORT}" --no-open --skip-build --tui --insecure'].join(''),
      '',
    ].join("\n"),
    require => [
      File["${install_dir}/bin"],
      Exec['install_hermes_agent'],
    ],
  }

  file { "${install_dir}/bin/agent-request-watch":
    ensure  => link,
    target  => "${broker_source_dir}/bin/agent-request-watch",
    require => [
      File["${install_dir}/bin"],
      Vcsrepo[$broker_source_dir],
    ],
  }

  file { "${install_dir}/bin/agent-request-response-watch":
    ensure  => link,
    target  => "${broker_source_dir}/bin/agent-request-response-watch",
    require => [
      File["${install_dir}/bin"],
      Vcsrepo[$broker_source_dir],
    ],
  }

  file { "${install_dir}/bin/agent-request-review-watch":
    ensure  => link,
    target  => "${broker_source_dir}/bin/agent-request-review-watch",
    require => [
      File["${install_dir}/bin"],
      Vcsrepo[$broker_source_dir],
    ],
  }


  file { "${systemd_user_dir}/hermes-gateway@.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Hermes Agent Gateway (%i)
      After=network-online.target ${hermes_environment_unit}
      Wants=network-online.target
      Requires=${hermes_environment_unit}
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
      Environment="SSH_AUTH_SOCK=%t/ssh-agent.socket"
      Environment="SSL_CERT_FILE="
      Environment="SSL_CERT_DIR=/etc/ssl/certs"
      Restart=always
      RestartSec=5
      RestartMaxDelaySec=300
      RestartSteps=5
      RestartForceExitStatus=75
      KillMode=mixed
      KillSignal=SIGTERM
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
      After=network-online.target ${hermes_environment_unit}
      Wants=network-online.target
      Requires=${hermes_environment_unit}
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

  file { "${systemd_user_dir}/hermes-agent-request-watch.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Watch Hermes agent requests for Talon review
      After=network-online.target ${hermes_environment_unit}
      Wants=network-online.target
      Requires=${hermes_environment_unit}

      [Service]
      Type=oneshot
      EnvironmentFile=${hermes_home_dir}/profiles/talon/systemd.env
      EnvironmentFile=${hermes_home_dir}/profiles/talon/.env
      ExecStart=${install_dir}/bin/agent-request-watch
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="PYTHONPATH=${pythonpath}"
      Environment="HERMES_HOME=${hermes_home_dir}"
      Environment="SSL_CERT_FILE="
      Environment="SSL_CERT_DIR=/etc/ssl/certs"
      StandardOutput=journal
      StandardError=journal
      | UNIT
    require => File["${install_dir}/bin/agent-request-watch"],
  }

  file { "${systemd_user_dir}/hermes-agent-request-watch.timer":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Poll Hermes agent requests for Talon review

      [Timer]
      OnBootSec=1min
      OnUnitActiveSec=1min
      AccuracySec=15s
      Unit=hermes-agent-request-watch.service

      [Install]
      WantedBy=timers.target
      | UNIT
    require => File["${systemd_user_dir}/hermes-agent-request-watch.service"],
  }

  file { "${systemd_user_dir}/hermes-agent-request-response-watch-star.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Deliver Hermes agent-request responses to Star
      After=network-online.target ${hermes_environment_unit}
      Wants=network-online.target
      Requires=${hermes_environment_unit}

      [Service]
      Type=oneshot
      EnvironmentFile=${hermes_home_dir}/profiles/star/systemd.env
      EnvironmentFile=${hermes_home_dir}/profiles/star/.env
      ExecStart=${install_dir}/bin/agent-request-response-watch star
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="PYTHONPATH=${pythonpath}"
      Environment="HERMES_HOME=${hermes_home_dir}"
      Environment="SSL_CERT_FILE="
      Environment="SSL_CERT_DIR=/etc/ssl/certs"
      StandardOutput=journal
      StandardError=journal
      | UNIT
    require => File["${install_dir}/bin/agent-request-response-watch"],
  }

  file { "${systemd_user_dir}/hermes-agent-request-response-watch-star.timer":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Poll Hermes agent-request responses for Star

      [Timer]
      OnBootSec=1min
      OnUnitActiveSec=1min
      AccuracySec=15s
      Unit=hermes-agent-request-response-watch-star.service

      [Install]
      WantedBy=timers.target
      | UNIT
    require => File["${systemd_user_dir}/hermes-agent-request-response-watch-star.service"],
  }

  file { "${systemd_user_dir}/hermes-agent-request-review-watch-talon.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Run Talon on Hermes agent requests marked for review
      After=network-online.target ${hermes_environment_unit}
      Wants=network-online.target
      Requires=${hermes_environment_unit}

      [Service]
      Type=oneshot
      EnvironmentFile=${hermes_home_dir}/profiles/talon/systemd.env
      EnvironmentFile=${hermes_home_dir}/profiles/talon/.env
      ExecStart=${install_dir}/bin/agent-request-review-watch talon
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="PYTHONPATH=${pythonpath}"
      Environment="HERMES_HOME=${hermes_home_dir}"
      Environment="SSL_CERT_FILE="
      Environment="SSL_CERT_DIR=/etc/ssl/certs"
      StandardOutput=journal
      StandardError=journal
      | UNIT
    require => File["${install_dir}/bin/agent-request-review-watch"],
  }

  file { "${systemd_user_dir}/hermes-agent-request-review-watch-talon.timer":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Poll Hermes agent requests for Talon agent review

      [Timer]
      OnBootSec=1min
      OnUnitActiveSec=1min
      AccuracySec=15s
      Unit=hermes-agent-request-review-watch-talon.service

      [Install]
      WantedBy=timers.target
      | UNIT
    require => File["${systemd_user_dir}/hermes-agent-request-review-watch-talon.service"],
  }

  file { "${systemd_user_dir}/hermes-gateway.service":
    ensure => absent,
  }

  file { "${systemd_user_dir}/hermes-dashboard.service":
    ensure => absent,
  }

  exec { 'disable_old_hermes_tars_units':
    command => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user disable --now hermes-gateway@tars.service hermes-dashboard@tars.service hermes-agent-request-response-watch-tars.timer || true\'',
    unless  => '/bin/sh -c \'! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-gateway@tars.service 2>/dev/null && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-gateway@tars.service 2>/dev/null && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-dashboard@tars.service 2>/dev/null && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-dashboard@tars.service 2>/dev/null && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-agent-request-response-watch-tars.timer 2>/dev/null && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-agent-request-response-watch-tars.timer 2>/dev/null\'',
    user    => $nest::user,
    require => Exec['enable_hermes_gateway_linger'],
  }

  [
    "${systemd_user_dir}/hermes-agent-request-response-watch-tars.service",
    "${systemd_user_dir}/hermes-agent-request-response-watch-tars.timer",
    "${systemd_user_dir}/default.target.wants/hermes-gateway@tars.service",
    "${systemd_user_dir}/default.target.wants/hermes-dashboard@tars.service",
    "${systemd_user_dir}/timers.target.wants/hermes-agent-request-response-watch-tars.timer",
  ].each |String[1] $old_tars_unit_path| {
    file { $old_tars_unit_path:
      ensure  => absent,
      require => Exec['disable_old_hermes_tars_units'],
    }
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

  File["${systemd_user_dir}/${hermes_environment_unit}"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-gateway@.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-dashboard@.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-agent-request-watch.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-agent-request-watch.timer"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-agent-request-response-watch-star.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-agent-request-response-watch-star.timer"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-agent-request-review-watch-talon.service"]
  ~>
  Exec['hermes-systemd-user-daemon-reload']

  File["${systemd_user_dir}/hermes-agent-request-review-watch-talon.timer"]
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
    command => "/usr/bin/loginctl enable-linger ${nest::user}",
    unless  => "/usr/bin/loginctl show-user ${nest::user} -p Linger --value | /bin/grep -qx yes",
  }

  exec { 'enable_hermes_agent_request_watch_timer':
    command => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-agent-request-watch.timer\'',
    unless  => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-agent-request-watch.timer && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-agent-request-watch.timer\'',
    user    => $nest::user,
    require => [
      Exec['enable_hermes_gateway_linger'],
      File["${systemd_user_dir}/hermes-agent-request-watch.timer"],
    ],
  }

  exec { 'enable_hermes_agent_request_response_watch_star_timer':
    command => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-agent-request-response-watch-star.timer\'',
    unless  => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-agent-request-response-watch-star.timer && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-agent-request-response-watch-star.timer\'',
    user    => $nest::user,
    require => [
      Exec['enable_hermes_gateway_linger'],
      File["${systemd_user_dir}/hermes-agent-request-response-watch-star.timer"],
    ],
  }

  exec { 'enable_hermes_agent_request_review_watch_talon_timer':
    command => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-agent-request-review-watch-talon.timer\'',
    unless  => '/bin/sh -c \'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-agent-request-review-watch-talon.timer && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-agent-request-review-watch-talon.timer\'',
    user    => $nest::user,
    require => [
      Exec['enable_hermes_gateway_linger'],
      File["${systemd_user_dir}/hermes-agent-request-review-watch-talon.timer"],
    ],
  }
}
