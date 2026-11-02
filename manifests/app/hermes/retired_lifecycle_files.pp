# Retain explicit tombstones so removing declarations also removes old files
class nest::app::hermes::retired_lifecycle_files {
  tag 'hermes_native_lifecycle_cutover'

  $systemd_user_dir = "/home/${nest::user}/.config/systemd/user"
  $install_dir = $nest::app::hermes::install_dir

  file { [
    "${systemd_user_dir}/hermes-agent-request-moving-tickets.service",
    "${systemd_user_dir}/hermes-agent-request-moving-tickets.timer",
    "${install_dir}/bin/agent-request-reconcile-moving-tickets",
  ]:
    ensure  => absent,
    require => Class['nest::app::hermes::retired_lifecycle'],
    notify  => Systemd::Daemon_reload['hermes-systemd-user-daemon-reload'],
  }
}
