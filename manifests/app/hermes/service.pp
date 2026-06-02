class nest::app::hermes::service (
  Stdlib::Absolutepath $install_dir               = '/opt/hermes-agent',
  Boolean              $dashboard_enabled         = false,
  String[1]            $dashboard_bind_host       = '0.0.0.0',
  Stdlib::Port         $dashboard_port            = 9119,
  Optional[String[1]]  $dashboard_oauth_client_id = undef,
) {
  $venv_dir                  = "${install_dir}/venv"
  $venv_python               = "${venv_dir}/bin/python"
  $hermes_home_dir           = "/home/${nest::user}/.hermes"
  $systemd_user_dir          = "/home/${nest::user}/.config/systemd/user"
  $hermes_gateway_dropin_dir = "${systemd_user_dir}/hermes-gateway.service.d"
  $hermes_environment_unit   = 'hermes-environment.service'

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


  file { "${systemd_user_dir}/hermes-gateway.service":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Hermes Agent Gateway - Messaging Platform Integration
      After=network-online.target
      Wants=network-online.target
      StartLimitIntervalSec=0

      [Service]
      Type=simple
      ExecStart=${venv_python} -m hermes_cli.main gateway run --replace
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="HERMES_HOME=${hermes_home_dir}"
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
  ->
  file { "${hermes_gateway_dropin_dir}/20-system-cert-trust.conf":
    ensure  => file,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => "[Service]\nEnvironment=SSL_CERT_FILE=\nEnvironment=SSL_CERT_DIR=/etc/ssl/certs\n",
  }

  if $dashboard_enabled and ($dashboard_bind_host in ['127.0.0.1', 'localhost', '::1'] or $dashboard_oauth_client_id) {
    $dashboard_service_ensure = file
    $dashboard_enable_command = '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-dashboard.service"'
    $dashboard_enable_unless  = '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-dashboard.service && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-dashboard.service"'
  } else {
    $dashboard_service_ensure = absent
    $dashboard_enable_command = '/bin/true'
    $dashboard_enable_unless  = '/bin/true'
  }

  file { "${systemd_user_dir}/hermes-dashboard.service":
    ensure  => $dashboard_service_ensure,
    mode    => '0644',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("UNIT"),
      [Unit]
      Description=Hermes Agent Dashboard
      After=network-online.target ${hermes_environment_unit}
      Wants=network-online.target
      Requires=${hermes_environment_unit}
      StartLimitIntervalSec=0

      [Service]
      Type=simple
      ExecStart=${venv_python} -m hermes_cli.main dashboard --host ${dashboard_bind_host} --port ${dashboard_port} --no-open --skip-build --tui
      WorkingDirectory=/home/${nest::user}
      Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      Environment="VIRTUAL_ENV=${venv_dir}"
      Environment="HERMES_HOME=${hermes_home_dir}"
      Environment="HERMES_DASHBOARD_TUI=1"
      Restart=always
      RestartSec=5
      StandardOutput=journal
      StandardError=journal

      [Install]
      WantedBy=default.target
      | UNIT
    require => Exec['install_hermes_agent'],
  }

  File["${systemd_user_dir}/hermes-dashboard.service"]
  ~>
  Exec['hermes-gateway-systemd-user-daemon-reload']

  exec { 'enable_hermes_dashboard_service':
    command => $dashboard_enable_command,
    unless  => $dashboard_enable_unless,
    user    => $nest::user,
    require => [
      Exec['enable_hermes_gateway_linger'],
      File["${systemd_user_dir}/hermes-dashboard.service"],
      File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"],
      File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"],
      File["${hermes_gateway_dropin_dir}/20-system-cert-trust.conf"],
    ],
  }


  File["${systemd_user_dir}/${hermes_environment_unit}"]
  ~>
  Exec['hermes-gateway-systemd-user-daemon-reload']


  File["${systemd_user_dir}/hermes-gateway.service"]
  ~>
  Exec['hermes-gateway-systemd-user-daemon-reload']

  File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"]
  ~>
  Exec['hermes-gateway-systemd-user-daemon-reload']

  File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"]
  ~>
  Exec['hermes-gateway-systemd-user-daemon-reload']

  File["${hermes_gateway_dropin_dir}/20-system-cert-trust.conf"]
  ~>
  Exec['hermes-gateway-systemd-user-daemon-reload']

  exec { 'hermes-gateway-systemd-user-daemon-reload':
    command     => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"',
    user        => $nest::user,
    refreshonly => true,
  }


  exec { 'enable_hermes_gateway_linger':
    command => "/usr/bin/loginctl enable-linger ${nest::user}",
    unless  => "/usr/bin/loginctl show-user ${nest::user} -p Linger --value | /bin/grep -qx yes",
  }

  exec { 'enable_hermes_gateway_service':
    command => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-gateway.service"',
    unless  => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-gateway.service && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-gateway.service"',
    user    => $nest::user,
    require => [
      Exec['enable_hermes_gateway_linger'],
      File["${systemd_user_dir}/hermes-gateway.service"],
      File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"],
      File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"],
      File["${hermes_gateway_dropin_dir}/20-system-cert-trust.conf"],
    ],
  }
}
