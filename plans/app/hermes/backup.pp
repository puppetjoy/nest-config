# Create a Hermes Agent backup archive on the target host.
#
# Uses Hermes' native backup command so restore semantics stay aligned with
# upstream Hermes state handling.
plan nest::app::hermes::backup (
  TargetSpec          $target       = 'owl',
  String[1]           $backup_dir   = '/nest/backup/hermes',
  Boolean             $quick        = false,
  String[1]           $user         = 'joy',
  Optional[String[1]] $namespace    = undef,
  Optional[String[1]] $service      = undef,
  String[1]           $service_name = 'talon',
) {
  if $quick {
    $command = @("COMMAND"/L)
      set -euo pipefail
      runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes backup --quick
      | COMMAND

    return run_command($command, $target, 'Create Hermes quick snapshot')
  }

  $timestamp = run_command('date +%Y%m%d-%H%M%S', $target, 'Timestamp Hermes backup').first.value['stdout'].chomp
  $archive   = "${backup_dir}/${service_name}-hermes-${timestamp}.zip"

  $command = @("COMMAND"/L)
    set -euo pipefail
    install -d -m 0700 -o ${user} -g ${user} ${backup_dir.shellquote}
    runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes backup --output ${archive.shellquote}
    chmod 0600 ${archive.shellquote}
    printf '%s\n' ${archive.shellquote}
    | COMMAND

  return run_command($command, $target, 'Create Hermes backup')
}
