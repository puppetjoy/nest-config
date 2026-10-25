# Collect the selected postboot gates once and hand them to native acceptance.
# No caller-supplied pass booleans, no failure clearing and no catalog replay.
plan nest::host::update_acceptance (
  TargetSpec          $target,
  Hash                $policy,
  Hash                $observations,
  Stdlib::Absolutepath $output_dir,
) {
  $nodes = get_targets($target)
  if $nodes.length != 1 {
    fail_plan('Acceptance requires exactly one host', 'nest/update-acceptance-target')
  }
  $name = $nodes[0].name
  $transaction = $observations[$name]['transaction']
  $context = { 'policy' => $policy, 'targets' => $observations.keys, 'inputs' => $observations,
    'output_dir' => $output_dir, 'host' => $name }
  $bound = run_task('nest::update_lifecycle', 'localhost', $context + { 'action' => 'inputs' }).first.value
  $status_command = ['nest', 'reset', 'status', $transaction, '--format=json'].shellquote
  $status = run_command($status_command, $name, { '_run_as' => 'root' }).first.value['stdout']
  $boot = run_task('nest::update_lifecycle', 'localhost', $context + { 'action' => 'boot', 'status' => $status }).first.value
  $settings = $policy['lifecycle']['acceptance'][$name]
  $retention = { 'transaction' => $transaction, 'release' => $bound['release'], 'output_dir' => $output_dir }
  $catalog_context = $context + { 'step' => 'catalog' }
  $catalog = run_task('nest::update_lifecycle', 'localhost', $catalog_context + { 'action' => 'read' }).first.value
  if !$catalog['complete'] {
    if $catalog['intent'] {
      fail_plan('Prior catalog outcome is ambiguous; inspect its private native reports before any apply', 'nest/update-lifecycle-ambiguous')
    }
    run_task('nest::update_lifecycle', 'localhost', $catalog_context + { 'action' => 'begin' })
    $catalog_outcome = run_plan('nest::host::update_catalog', {
      'target' => $name, 'expectations' => {
        'hostname' => $name, 'certname' => $settings['certname'],
        'boot_id' => parsejson($status)['observation']['boot_id'], 'configuration_version' => $policy['config_source'],
      }, 'retention' => $retention,
    })
    run_task('nest::update_lifecycle', 'localhost', $catalog_context + { 'action' => 'complete', 'result' => $catalog_outcome['retained_report'] })
    if $catalog_outcome['result'] != 'pass' {
      fail_plan('Main apply or unchanged repeat failed; retain failure and stop', 'nest/update-lifecycle-catalog')
    }
  }
  $health_context = $context + { 'step' => 'health' }
  $health = run_task('nest::update_lifecycle', 'localhost', $health_context + { 'action' => 'read' }).first.value
  if !$health['complete'] {
    if $health['intent'] {
      fail_plan('Prior health retention is incomplete; inspect before continuing', 'nest/update-lifecycle-ambiguous')
    }
    run_task('nest::update_lifecycle', 'localhost', $health_context + { 'action' => 'begin' })
    $health_outcome = run_plan('nest::host::update_health', {
      'target' => $name, 'expectations' => $boot, 'endpoints' => $settings['endpoints'], 'retention' => $retention,
    })
    run_task('nest::update_lifecycle', 'localhost', $health_context + { 'action' => 'complete', 'result' => $health_outcome['retained_report'] })
  }
  $settings['canaries'].each |$canary| {
    $canary_context = $context + { 'step' => "canary-${canary['name']}" }
    $previous = run_task('nest::update_lifecycle', 'localhost', $canary_context + { 'action' => 'read' }).first.value
    if !$previous['complete'] {
      if $previous['intent'] {
        fail_plan('Prior canary outcome is ambiguous; never replay automatically', 'nest/update-lifecycle-ambiguous')
      }
      run_task('nest::update_lifecycle', 'localhost', $canary_context + { 'action' => 'begin' })
      # Reviewed argv, ordinary inventory user, bounded command timeout. Never
      # record arbitrary output, use root SSH or clear historical failures.
      $canary_before = run_command($status_command, $name, { '_run_as' => 'root' }).first.value['stdout']
      $canary_result = run_command($canary['command'].shellquote, $name, { '_catch_errors' => true, '_timeout' => 60 })
      $after = run_command($status_command, $name, { '_run_as' => 'root' }).first.value['stdout']
      if parsejson($canary_before)['observation']['boot_id'] != parsejson($after)['observation']['boot_id'] {
        fail_plan('Boot changed during canary; no acceptance', 'nest/update-lifecycle-canary-boot')
      }
      $receipt = run_task('nest::update_lifecycle', 'localhost', $context + {
        'action' => 'canary', 'canary' => $canary['name'], 'status' => $after,
        'native_exit' => $canary_result.first.value['exit_code'],
      }).first.value
      run_task('nest::update_lifecycle', 'localhost', $canary_context + { 'action' => 'complete', 'result' => $receipt })
    }
  }
  $after = run_command($status_command, $name, { '_run_as' => 'root' }).first.value['stdout']
  $evidence = run_task('nest::update_lifecycle', 'localhost', $context + { 'action' => 'evidence', 'status' => $after }).first.value
  $accepted = run_task('nest::update_accept', $name, {
    'transaction' => $transaction, 'evidence' => $evidence['evidence'], '_run_as' => 'root',
  }).first.value
  # Reopen the live accepted status before finalization; returned task transport
  # success alone never asserts acceptance or boot identity.
  $live = run_command($status_command, $name, { '_run_as' => 'root' }).first.value['stdout']
  $receipt = run_task('nest::retain_update_report', 'localhost', {
    'report' => $live, 'transaction' => $transaction, 'release' => $bound['release'], 'hostname' => $name, 'output_dir' => $output_dir,
  }).first.value
  unless $accepted['accepted'] == true and $receipt['cli_accepted'] == true and $receipt['observation_retained'] == true {
    fail_plan('Native acceptance was not observed and retained', 'nest/update-acceptance-retention')
  }
  return({ 'evidence' => $evidence.filter |$key, $value| { $key != 'evidence' }, 'accepted' => $receipt })
}
