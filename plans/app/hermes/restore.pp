# Restore Hermes Agent state from a native Hermes backup archive.
#
# By default this refuses to overwrite existing files; pass force=true for the
# native Hermes import --force behavior.
plan nest::app::hermes::restore (
  String[1]  $archive,
  TargetSpec $target = 'owl',
  Boolean    $force  = false,
  String[1]  $user   = 'joy',
) {
  $force_flag = $force ? {
    true    => '--force',
    default => '',
  }

  $command = @("COMMAND"/L)
    set -euo pipefail
    test -f ${archive.shellquote}
    systemctl --user -M ${user}@ stop hermes-gateway.service || true
    systemctl --user -M ${user}@ stop hermes-dashboard.service || true
    runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes import ${force_flag} ${archive.shellquote}
    systemctl --user -M ${user}@ start hermes-gateway.service || true
    systemctl --user -M ${user}@ start hermes-dashboard.service || true
    | COMMAND

  return run_command($command, $target, 'Restore Hermes backup')
}
