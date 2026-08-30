# Create a Hermes Agent backup archive on the target host.
#
# Uses Hermes' native backup command so restore semantics stay aligned with
# upstream Hermes state handling.
plan nest::app::hermes::backup (
  TargetSpec          $target       = 'owl',
  String[1]           $backup_dir   = '/nest/backup/hermes',
  Boolean             $quick        = false,
  String[1]           $user         = 'joy',
  Integer[1]          $retain       = 24,
  # Deprecated alias for profile.
  String[1]           $service_name = 'talon',
  Optional[String[1]] $profile      = undef,
) {
  $profile_name = $profile ? {
    undef   => $service_name,
    default => $profile,
  }

  if $quick {
    $command = @("COMMAND"/L)
      set -euo pipefail
      runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes --profile ${profile_name.shellquote} backup --quick
      | COMMAND

    return run_command($command, $target, 'Create Hermes quick snapshot', {
      '_run_as' => 'root',
    })
  }

  $timestamp = run_command('date +%Y%m%d-%H%M%S', $target, 'Timestamp Hermes backup').first.value['stdout'].chomp
  $archive   = "${backup_dir}/${profile_name}-hermes-${timestamp}.zip"

  $command = @("COMMAND"/L)
    set -euo pipefail
    install -d -m 0700 -o ${user} -g ${user} ${backup_dir.shellquote}
    runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes --profile ${profile_name.shellquote} backup --output ${archive.shellquote}
    chmod 0600 ${archive.shellquote}
    find ${backup_dir.shellquote} -maxdepth 1 -type f -name ${"${profile_name}-hermes-*.zip".shellquote} -print0 \
      | sort -z \
      | head -z -n -${retain} \
      | xargs -0r rm --
    printf '%s\n' ${archive.shellquote}
    | COMMAND

  return run_command($command, $target, 'Create Hermes backup', {
    '_run_as' => 'root',
  })
}
