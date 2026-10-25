# Dispatch/inspect a lifecycle on an existing surviving controller; inspect by
# default. Export copies actual sanitized report bytes back to this supervisor.
plan nest::host::update_dispatch (
  TargetSpec                                   $controller,
  Stdlib::Absolutepath                         $project,
  Pattern[/\A[0-9a-f]{40}\z/]                  $source,
  Hash                                         $params,
  Enum['inspect', 'start', 'resume', 'export'] $action     = 'inspect',
  Optional[Stdlib::Absolutepath]               $output_dir = undef,
) {
  $nodes = get_targets($controller)
  if $nodes.length != 1 or $nodes[0].name != $params['policy']['lifecycle']['controller'] {
    fail_plan('Dispatch requires the exact surviving inventory controller', 'nest/update-dispatch-target')
  }
  if ($action == 'export') != ($output_dir != undef) {
    fail_plan('Only export requires a local existing output_dir', 'nest/update-dispatch-output')
  }
  $result = run_task('nest::update_dispatch', $nodes[0], {
    'project' => $project, 'source' => $source, 'params' => $params, 'action' => $action,
  }).first.value
  if $action == 'export' {
    return(run_task('nest::update_dispatch', 'localhost', {
      'action' => 'receive', 'export' => $result, 'output_dir' => $output_dir,
    }).first.value)
  }
  return($result)
}
