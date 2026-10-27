# Create one verified full-Hermes-home backup generation per checkpoint.
#
# Hermes' native full backup always scans the default Hermes root, regardless
# of --profile.  Profile/service parameters remain accepted for compatibility
# with old callers, but never label or multiply full-home archives.
plan nest::app::hermes::backup (
  TargetSpec                          $target                 = 'owl',
  String[1]                           $backup_dir             = '/nest/backup/hermes',
  String[1]                           $stage_dir              = '/var/tmp/nest-hermes-backup',
  Boolean                             $preserve_existing      = false,
  Boolean                             $verify_only            = false,
  Optional[String[64, 64]]            $expected_sha256        = undef,
  Optional[Integer[1, 604800]]        $max_age_seconds        = undef,
  Optional[Hash]                      $verification_retention = undef,
  Boolean                             $quick                  = false,
  Boolean                             $prune_only             = false,
  Boolean                             $cleanup_legacy         = false,
  Boolean                             $apply_legacy_cleanup   = false,
  Optional[String[1]]                 $checkpoint             = undef,
  # Account used to run Hermes and own the backup directory.
  String[1]                           $user                   = 'joy',
  Integer[1]                          $retain                 = 24,
  Array[String[1], 1]                 $required_profiles      = ['talon', 'star', 'beryl', 'quill'],
  # Deprecated compatibility inputs. Full backups are deliberately unscoped.
  Optional[String[1]]                 $service_name           = undef,
  Optional[String[1]]                 $profile                = undef,
) {
  if $verification_retention != undef and !$verify_only {
    fail_plan('verification_retention applies only to explicit verify_only calls', 'nest/update-backup-retention')
  }
  if $verify_only {
    if $quick or $prune_only or $cleanup_legacy or $apply_legacy_cleanup or $preserve_existing or
      $checkpoint == undef or $expected_sha256 !~ Pattern[/\A[0-9a-f]{64}\z/] or $max_age_seconds == undef {
      fail_plan('verify_only requires exact checkpoint, expected_sha256 and max_age_seconds; refuses all capture and cleanup modes')
    }
  } elsif $expected_sha256 != undef or $max_age_seconds != undef {
    fail_plan('expected_sha256 and max_age_seconds require verify_only=true')
  }
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
      '/usr/local/bin/hermes', '--profile', $quick_profile,
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
  if $verification_retention != undef {
    $verification_check = {
      'kind'              => 'hermes',
      'target'            => $backup_target.name,
      'user'              => $user,
      'backup_dir'        => $backup_dir,
      'checkpoint'        => $checkpoint,
      'expected_sha256'   => $expected_sha256,
      'max_age_seconds'   => $max_age_seconds,
      'required_profiles' => $required_profiles,
    }
    # Check the supervisor destination before upload or native verification.
    run_task('nest::retain_update_backup', 'localhost', {
      'action'    => 'check',
      'check'     => $verification_check,
      'retention' => $verification_retention,
    })
  }
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
  if $verify_only {
    $helper_args = [
      $helper, 'verify',
      '--backup-dir', $backup_dir,
      '--checkpoint', $checkpoint,
      '--expected-sha256', $expected_sha256,
      '--max-age-seconds', String($max_age_seconds),
    ] + $required_profile_args
    $description = 'Verify exact existing Hermes generation without capture or pruning'
  } elsif $prune_only {
    $helper_args = [
      $helper, 'prune',
      '--backup-dir', $backup_dir,
      '--retain', String($retain),
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
    $retention_args = $preserve_existing ? {
      true    => ['--no-prune'],
      default => [],
    }
    $helper_args = [
      $helper, 'backup',
      '--backup-dir', $backup_dir,
      '--hermes-bin', '/usr/local/bin/hermes',
      '--stage-dir', $stage_dir,
      '--retain', String($retain),
    ] + $required_profile_args + $checkpoint_args + $retention_args
    $description = 'Create or reuse Hermes full-home backup generation'
  }

  $initialize_directory = $verify_only ? {
    true    => 'true',
    default => ['install', '-d', '-m', '0700', '-o', $user, '-g', $user, $backup_dir].shellquote,
  }
  $command = @("COMMAND"/L)
    set -euo pipefail
    trap 'rm -f ${helper}' EXIT HUP INT TERM
    ${initialize_directory}
    chown ${user.shellquote}:${user.shellquote} ${helper.shellquote}
    chmod 0700 ${helper.shellquote}
    # Rootless Podman overlay files are owned by subordinate host UIDs. Enter
    # the backup user's existing user namespace so the full-home archive can
    # read them without changing their ownership or omitting any state.
    # Bolt's root run-as shell may start in /root, which Podman cannot enter
    # after runuser drops privileges.
    cd /
    runuser -u ${user.shellquote} -- podman unshare ${helper_args.shellquote}
    | COMMAND

  $result = run_command($command, $backup_target, $description, {
    '_run_as' => 'root',
  })
  if $verification_retention != undef {
    return(run_task('nest::retain_update_backup', 'localhost', {
      'action'    => 'retain',
      'check'     => $verification_check,
      'retention' => $verification_retention,
      'report'    => $result.results[0].value['stdout'],
    }).results[0].value)
  }
  return $result
}
