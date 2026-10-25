# @summary Independently reopen a sealed Stage 3 root on its native publication host
plan nest::build::check_stage3_root (
  TargetSpec    $targets,
  Array[String] $arguments,
) {
  $nodes = get_targets($targets)
  unless $nodes.length == 1 {
    fail('Stage 3 admission requires one publication host')
  }
  return(parsejson(run_script('nest/build/check-stage3-root.py', $nodes,
    { 'arguments' => $arguments, '_run_as' => 'root' }).first.value['stdout']))
}
