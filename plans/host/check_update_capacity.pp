# Observe native capacity for one exact preparation input; never prepare or resume.
# Full release and seal reconciliation remains the enclosing update plan's job.
plan nest::host::check_update_capacity (
  TargetSpec                        $target,
  Pattern[/\Asha256:[0-9a-f]{64}\z/] $release,
  Hash                              $inputs,
  Stdlib::Absolutepath               $output_dir,
  Optional[Hash]                    $binding = undef,
) {
  if $binding != undef and ($binding.keys.sort != ['policy_sha256', 'stage', 'transaction'] or
    $binding['transaction'] != $inputs['transaction'] or
    $binding['policy_sha256'] !~ Pattern[/\A[0-9a-f]{64}\z/] or
    !($binding['stage'] in ['preflight', 'initiation'])) {
    fail_plan('Invalid capacity preparation association; no host contacted', 'nest/update-capacity-binding')
  }
  $association = $binding ? {
    undef   => {},
    default => { 'binding' => $binding },
  }
  $nodes = get_targets($target)
  if $nodes.length != 1 or $nodes[0].name =~ Pattern[/\A[^.]*-console(?:\.|\z)/] {
    fail_plan('Capacity observation requires one non-console inventory host', 'nest/update-capacity-target')
  }
  # Reuse existing destination validation before the first host command.
  run_task('nest::retain_update_report', 'localhost', {
    'action'      => 'check',
    'transaction' => $inputs['transaction'],
    'release'     => $release,
    'hostname'    => $nodes[0].name,
    'output_dir'  => $output_dir,
  })
  $argv = ['nest', 'reset', '--plan', '--release', $release,
    '--root-generation', $inputs['root_generation'], '--capacity-policy', $inputs['capacity_policy'], '--format=json']
  $native = run_command($argv.shellquote, $nodes[0], 'Observe native reset capacity without mutation', {
    '_run_as' => 'root',
  })
  return(run_task('nest::retain_update_preflight', 'localhost', {
    'report'     => $native.results[0].value['stdout'],
    'hostname'   => $nodes[0].name,
    'release'    => $release,
    'inputs'     => $inputs,
    'output_dir' => $output_dir,
  } + $association).results[0].value)
}
