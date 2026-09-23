# Create one verified full-Hermes-home backup generation per checkpoint.
#
# Hermes' native full backup always scans the default Hermes root, regardless
# of --profile.  Profile/service parameters remain accepted for compatibility
# with old callers, but never label or multiply full-home archives.
plan nest::app::hermes::backup (
  TargetSpec           $target               = 'owl',
  String[1]            $backup_dir           = '/nest/backup/hermes',
  Boolean              $quick                = false,
  Boolean              $prune_only           = false,
  Boolean              $cleanup_legacy       = false,
  Boolean              $apply_legacy_cleanup = false,
  Optional[String[1]]  $checkpoint           = undef,
  # Account used to run Hermes and own the backup directory.
  String[1]            $user                 = 'joy',
  Integer[1]           $retain               = 24,
  Array[String[1], 1]  $required_profiles    = ['talon', 'star', 'beryl', 'quill'],
  # Deprecated compatibility inputs. Full backups are deliberately unscoped.
  Optional[String[1]]  $service_name         = undef,
  Optional[String[1]]  $profile              = undef,
) {
  if $quick and ($prune_only or $cleanup_legacy) {
    fail_plan('quick, prune_only, and cleanup_legacy are mutually exclusive')
  }
  if $prune_only and $cleanup_legacy {
    fail_plan('quick, prune_only, and cleanup_legacy are mutually exclusive')
  }
  if $apply_legacy_cleanup and !$cleanup_legacy {
    fail_plan('apply_legacy_cleanup requires cleanup_legacy=true')
  }

  if $quick {
    $quick_profile = $profile ? {
      undef   => $service_name ? {
        undef   => 'talon',
        default => $service_name,
      },
      default => $profile,
    }
    $command = [
      'runuser', '-u', $user, '--',
      '/opt/hermes-agent/venv/bin/hermes', '--profile', $quick_profile,
      'backup', '--quick',
    ].shellquote

    return run_command($command, $target, 'Create profile quick snapshot', {
      '_run_as' => 'root',
    })
  }

  $backup_targets = get_targets($target)
  if $backup_targets.length != 1 {
    fail_plan('Hermes backup requires exactly one shared backup target')
  }
  $backup_target = $backup_targets[0]
  $helper = run_command(
    'mktemp /tmp/nest-hermes-backup-generation.XXXXXXXX',
    $backup_target,
    'Create unique Hermes backup helper path',
    { '_run_as' => 'root' },
  ).first.value['stdout'].chomp

  upload_file('nest/hermes-backup-generation', $helper, $backup_target, {
    '_run_as' => 'root',
  })

  $required_profile_args = $required_profiles.map |$required_profile| {
    ['--required-profile', $required_profile]
  }.flatten
  if $prune_only {
    $helper_args = [
      $helper, 'prune',
      '--backup-dir', $backup_dir,
      '--retain', $retain,
    ] + $required_profile_args
    $description = 'Prune Hermes full-home backup generations'
  } elsif $cleanup_legacy {
    $apply_args = $apply_legacy_cleanup ? {
      true    => ['--apply'],
      default => [],
    }
    $helper_args = [
      $helper, 'legacy-cleanup',
      '--backup-dir', $backup_dir,
    ] + $required_profile_args + $apply_args
    $description = $apply_legacy_cleanup ? {
      true    => 'Apply Hermes legacy archive cleanup with readback',
      default => 'Dry-run Hermes legacy archive cleanup',
    }
  } else {
    $checkpoint_args = $checkpoint ? {
      undef   => [],
      default => ['--checkpoint', $checkpoint],
    }
    $helper_args = [
      $helper, 'backup',
      '--backup-dir', $backup_dir,
      '--hermes-bin', '/opt/hermes-agent/venv/bin/hermes',
      '--retain', $retain,
    ] + $required_profile_args + $checkpoint_args
    $description = 'Create or reuse Hermes full-home backup generation'
  }

  $command = @("COMMAND"/L)
    set -euo pipefail
    trap 'rm -f ${helper}' EXIT HUP INT TERM
    install -d -m 0700 -o ${user.shellquote} -g ${user.shellquote} ${backup_dir.shellquote}
    chmod 0700 ${helper.shellquote}
    runuser -u ${user.shellquote} -- ${helper_args.shellquote}
    | COMMAND

  $result = run_command($command, $backup_target, $description, {
    '_run_as' => 'root',
  })
  return $result
}
