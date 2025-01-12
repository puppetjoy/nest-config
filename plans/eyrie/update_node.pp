# Update Eyrie node
#
# @param targets Eyrie nodes to update
# @param kubelet_version Hold back to this version pending cluster upgrade
plan nest::eyrie::update_node (
  TargetSpec $targets,
  String     $kubelet_version = '1.30'
) {
  get_targets($targets).each |$target| {
    run_plan('nest::kubernetes::drain_node', $target)
    run_plan('nest::puppet::run', $target, { 'tags' => ['cli'] })
    run_command('rm -rf /usr/lib/debug/*', $target, 'Remove old debug data', { '_catch_errors' => true })
    run_plan('nest::host::update', $target, { 'reboot' => true })
    run_command('emerge --oneshot --verbose "<=sys-cluster/kubelet-${kubelet_version}.9999" && systemctl restart kubelet', $target, 'Downgrade kubelet', {
      '_env_vars' => { 'kubelet_version' => $kubelet_version },
      '_run_as'   => 'root'
    })
    run_plan('nest::kubernetes::uncordon_node', $target)
  }
}
