# Observe exact native reboot continuity after a lost result or controller restart.
# Reopens original supervisor admission first; never submits, retries or accepts.
plan nest::host::observe_update_reboot (
  TargetSpec                                      $target,
  Pattern[/\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\z/]      $transaction,
  Pattern[/\Asha256:[0-9a-f]{64}\z/]                 $release,
  String[1]                                       $hostname,
  Stdlib::Absolutepath                             $output_dir,
  Hash                                            $admission,
) {
  $nodes = get_targets($target)
  if $nodes.length != 1 or $nodes[0].name =~ Pattern[/\A[^.]*-console(?:\.|\z)/] {
    fail_plan('Reboot observation requires exactly one non-console host', 'nest/update-reboot-observation-target')
  }
  $context = {
    'transaction' => $transaction,
    'release'     => $release,
    'hostname'    => $hostname,
    'output_dir'  => $output_dir,
    'admission'   => $admission,
  }
  run_task('nest::retain_update_reboot_observation', 'localhost', $context + { 'action' => 'check' })
  # Reconnect is not acceptance. A transport failure stops this invocation;
  # a later invocation only repeats this read, never a reboot or preparation.
  $native = run_command(
    ['nest', 'reset', 'status', $transaction, '--format=json'].shellquote,
    $nodes[0], 'Observe exact transaction boot without submitting a reboot', { '_run_as' => 'root' },
  )
  $receipt = run_task('nest::retain_update_reboot_observation', 'localhost', $context + {
    'action' => 'retain',
    'report' => $native.first.value['stdout'],
  }).first.value
  unless $receipt['readback_verified'] == true and $receipt['transaction'] == $transaction and
    $receipt['release'] == $release and $receipt['hostname'] == $hostname and $receipt['read_only'] == true and
    $receipt['execution_requested'] == false and $receipt['acceptance_recorded'] == false and
    $receipt['resubmission_allowed'] == false and $receipt['target_boot_observed'] =~ Boolean and
    $receipt['submission_outcome'] in ['not_attempted', 'unknown', 'returned_success', 'returned_failure'] and
    (!$receipt['target_boot_observed'] or $receipt['submission_outcome'] != 'not_attempted') {
    fail_plan('Reboot continuity was not retained with exact readback; never resubmit', 'nest/update-reboot-observation-retention')
  }
  return($receipt)
}
