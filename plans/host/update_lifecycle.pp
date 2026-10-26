# Continue already prepared transactions. Preview by default; never prepares or
# falls back to legacy reboot. Run on the policy's surviving external controller.
plan nest::host::update_lifecycle (
  TargetSpec                    $targets,
  Hash                          $policy,
  Hash                          $observations,
  Stdlib::Absolutepath           $output_dir,
  Boolean                       $execute     = false,
  Optional[Hash]                $maintenance = undef,
) {
  $nodes = get_targets($targets)
  $names = $nodes.map |$node| { $node.name }
  $context = { 'policy' => $policy, 'targets' => $names, 'inputs' => $observations, 'output_dir' => $output_dir }
  $bound = run_task('nest::update_lifecycle', 'localhost', $context + { 'action' => 'inputs' }).first.value
  $controllers = $names.filter |$name| { $name in ['control1', 'control2', 'control3'] }
  if $names.any |$name| { $name =~ Pattern[/\Acontrol[123]\./] } or
    (!$controllers.empty and ($maintenance == undef or $maintenance.keys.sort != $controllers.sort)) or
    ($controllers.empty and $maintenance != undef) {
    fail_plan('Lifecycle requires canonical controller names and exact maintenance scope', 'nest/maintenance-scope')
  }
  if $bound['waves'].any |$wave| { $wave.any |$name| { $name in $controllers } and $wave.length != 1 } {
    fail_plan('Controller outages must be isolated from every other host', 'nest/maintenance-wave')
  }
  if $execute {
    # The task observes the actual supervisor hostname, including when Bolt is
    # containerized. It must be the reviewed controller, outside the target set.
    run_task('nest::update_controller', 'localhost', { 'controller' => $policy['lifecycle']['controller'] })
  }
  # ALL hosts must have complete native preparation before the first reboot.
  # A failed/unknown preparation can never enter the submission set.
  $admissions = $names.reduce({}) |$memo, $name| {
    $step = $context + { 'host' => $name, 'step' => 'reboot' }
    $prior = run_task('nest::update_lifecycle', 'localhost', $step + { 'action' => 'read' }).first.value
    if $prior['complete'] {
      $admission = $prior['receipt']
    } else {
      $admission = run_plan('nest::host::check_update_reboot', {
        'target' => $name, 'transaction' => $observations[$name]['transaction'],
        'release' => $bound['release'], 'hostname' => $name, 'output_dir' => $output_dir,
      })
      if $execute {
        run_task('nest::update_lifecycle', 'localhost', $step + { 'action' => 'complete', 'result' => $admission })
      }
    }
    $memo + { $name => $admission }
  }
  if !$execute {
    return({ 'kind' => 'nest_update_lifecycle_preview', 'schema' => 1, 'policy_sha256' => $bound['policy_sha256'],
      'admissions' => $admissions, 'execution_requested' => false, 'acceptance_recorded' => false })
  }
  $waves = $bound['waves'].map |$wave| {
    $wave_results = parallelize($wave) |$name| {
      $outcome = catch_errors() || {
      $transaction = $observations[$name]['transaction']
      $host_context = $context + { 'host' => $name }
      # A native intent, lost transport reply or controller restart only enters
      # observation. The CLI additionally enforces at-most-once submission.
      $before = run_plan('nest::host::observe_update_reboot', {
        'target' => $name, 'transaction' => $transaction, 'release' => $bound['release'],
        'hostname' => $name, 'output_dir' => $output_dir, 'admission' => $admissions[$name], 'reconnect_timeout' => 600,
      })
      if $before['submission_outcome'] == 'not_attempted' {
        # A separate submission marker closes the controller-crash gap before
        # native intent is durable. Its existence never authorizes a retry.
        $submit = $host_context + { 'step' => 'submit' }
        $submitted = run_task('nest::update_lifecycle', 'localhost', $submit + { 'action' => 'read' }).first.value
        if $submitted['intent'] {
          fail_plan('Reboot initiation is ambiguous; inspect native status, never resubmit', 'nest/update-lifecycle-ambiguous')
        }
        run_task('nest::update_lifecycle', 'localhost', $host_context + { 'action' => 'admit' })
        if $name in $controllers {
          run_plan('nest::kubernetes::check_control_plane_maintenance', $maintenance[$name] + { 'target' => $name })
        }
        $bound['backup_requirements'][$name].each |$check| {
          run_plan('nest::host::check_update_backup', {
            'check' => $check,
            'retention' => { 'transaction' => $transaction, 'release' => $bound['release'], 'hostname' => $name,
              'policy_sha256' => $bound['policy_sha256'], 'stage' => 'initiation', 'output_dir' => $output_dir },
          })
        }
        run_task('nest::update_lifecycle', 'localhost', $host_context + { 'action' => 'admit' })
        run_task('nest::update_lifecycle', 'localhost', $submit + { 'action' => 'begin' })
        # Do not interpret a disconnect as success or retry the command. Its
        # persisted native intent and actual next boot determine continuation.
        run_command(['nest', 'reset', 'reboot', $transaction, '--execute', '--format=json'].shellquote, $name, {
          '_run_as' => 'root', '_catch_errors' => true,
        })
      }
      # A still-reachable old boot is not readiness. Poll its actual boot ID
      # with a finite budget; connection loss uses the existing bounded Bolt
      # reconnect. No second submission or wait-for-disconnect is involved.
      $observed = range(0, 11).reduce($before) |$previous, $attempt| {
        if $previous['target_boot_observed'] == true {
          $previous
        } else {
          if $attempt > 0 {
            run_command('sleep 5', 'localhost', 'Bound the next native boot observation')
          }
          run_plan('nest::host::observe_update_reboot', {
            'target' => $name, 'transaction' => $transaction, 'release' => $bound['release'],
            'hostname' => $name, 'output_dir' => $output_dir, 'admission' => $admissions[$name], 'reconnect_timeout' => 600,
          })
        }
      }
      if $observed['target_boot_observed'] != true {
        fail_plan('Expected target boot is not observed yet; resume observation only, never reboot again', 'nest/update-lifecycle-await-boot')
      }
      $accepted = run_plan('nest::host::update_acceptance', {
        'target' => $name, 'policy' => $policy, 'observations' => $observations, 'output_dir' => $output_dir,
      })
      $finalized = run_plan('nest::host::update_finalize', {
        'target' => $name, 'transaction' => $transaction, 'release' => $bound['release'], 'hostname' => $name,
        'output_dir' => $output_dir, 'execute' => true,
      })
      $host_result = { 'hostname' => $name, 'boot' => $observed, 'acceptance' => $accepted, 'finalization' => $finalized }
      $host_result
      }
      $outcome
    }
    $failed = $wave_results.filter |$entry| { $entry =~ Error }
    if !$failed.empty {
      fail_plan("Lifecycle wave stopped; retained phase evidence remains available: ${failed[0].message}", 'nest/update-lifecycle-wave')
    }
    $wave_results
  }
  # The existing publisher copies/reopens exact sanitized documents on this
  # persistent controller. Dispatch also exports these files to its caller.
  $report = { 'schema' => 1, 'kind' => 'nest_update_lifecycle', 'policy_sha256' => $bound['policy_sha256'],
    'release' => $bound['release'], 'waves' => $waves, 'host_count' => $names.length,
    'retention' => $policy['lifecycle']['retention'], 'physical_ux' => 'not_observed' }
  $retained = run_task('nest::update_lifecycle', 'localhost', $context + { 'action' => 'retain', 'report' => $report }).first.value
  return($report + { 'retained_report' => $retained })
}
