# Upgrade Kubernetes and kubelet
#
# @param targets Nodes to upgrade
plan nest::kubernetes::upgrade_node (
  TargetSpec $targets
) {
  run_command('eix-sync -a', $targets)

  get_targets($targets).each |$target| {
    run_command('kubeadm upgrade node', $target)
    run_command('emerge --oneshot --verbose kubelet', $target)
    run_command('systemctl restart kubelet', $target)
  }
}
