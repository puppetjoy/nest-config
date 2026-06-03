# Restore Hermes Agent state from a native Hermes backup archive.
#
# By default this refuses to overwrite existing files; pass force=true for the
# native Hermes import --force behavior.
plan nest::app::hermes::restore (
  String[1]  $archive,
  TargetSpec $target  = 'owl',
  Boolean    $force   = false,
  String[1]  $user    = 'joy',
  String[1]  $profile = 'talon',
) {
  $force_flag = $force ? {
    true    => '--force',
    default => '',
  }

  $command = @("COMMAND"/L)
    set -euo pipefail
    test -f ${archive.shellquote}
    systemctl --user -M ${user}@ stop hermes-gateway@${profile}.service || true
    systemctl --user -M ${user}@ stop hermes-dashboard@${profile}.service || true
    runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes --profile ${profile.shellquote} import ${force_flag} ${archive.shellquote}
    systemctl --user -M ${user}@ start hermes-gateway@${profile}.service || true
    systemctl --user -M ${user}@ start hermes-dashboard@${profile}.service || true
    | COMMAND

  return run_command($command, $target, 'Restore Hermes backup')
}
