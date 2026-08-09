# Upgrade Kubernetes and kubelet
#
# @param targets Nodes to upgrade
plan nest::kubernetes::upgrade_node (
  TargetSpec $targets
) {
  run_command('eix-sync -a', $targets, {
    _run_as => 'root',
  })

  get_targets($targets).each |$target| {
    run_command('kubeadm upgrade node --ignore-preflight-errors=SystemVerification --patches=/etc/kubernetes/patches', $target, {
      _run_as => 'root',
    })
    run_command('emerge --oneshot --verbose kubelet', $target, {
      _run_as => 'root',
    })
    run_command('systemctl restart kubelet', $target, {
      _run_as => 'root',
    })
  }
}
