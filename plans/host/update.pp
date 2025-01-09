# Update the operating system
#
# @param $targets Nodes to update
# @param $reset Update using reset method
# @param $reboot Reboot the system after updating
# @param $run_puppet Run Puppet to complete update (only if rebooted)
plan nest::host::update (
  TargetSpec $targets,
  Boolean    $reset      = true,
  Boolean    $reboot     = false,
  Boolean    $run_puppet = true,
) {
  if $reset {
    $verb = 'reset'
  } else {
    $verb = 'update'
  }

  $results = run_command("nest ${verb}", $targets, "${verb.capitalize} the operating system", _catch_errors => true)

  # One-time workaround for rsync failure due to image building changes
  # XXX Remove after Jan 2025
  run_command("nest ${verb} --resume", $results.error_set.targets, "Resume ${verb} after error")

  if $reboot {
    run_plan('nest::host::reboot', $targets, _description => 'Reboot the system')

    if $run_puppet {
      run_plan('nest::puppet::run', $targets, _description => 'Run Puppet to complete update')
    }
  }
}
