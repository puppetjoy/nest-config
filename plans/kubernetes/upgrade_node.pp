# Upgrade Kubernetes and kubelet
#
# @param targets Nodes to upgrade
plan nest::kubernetes::upgrade_node (
  TargetSpec    $targets,
  Array[String] $etcd_servers     = [],
  Boolean       $sync             = true,
  Boolean       $upgrade_kubelet  = true,
) {
  $nodes = get_targets($targets)
  $control_plane_nodes = $nodes.filter |$target| {
    run_command('if test -f /etc/kubernetes/manifests/kube-apiserver.yaml; then printf true; else printf false; fi', $target, 'Classify Kubernetes node role before mutation', {
      _run_as => 'root',
    }).first.value['stdout'].chomp == 'true'
  }
  if !$control_plane_nodes.empty and $etcd_servers.empty {
    $control_plane_names = $control_plane_nodes.map |$target| { $target.name }
    fail("Control-plane upgrade for ${control_plane_names.join(', ')} requires explicit final etcd_servers for strict reconciliation")
  }

  if $sync {
    run_command('eix-sync -a', $targets, {
      _run_as => 'root',
    })
  }

  $nodes.each |$target| {
    run_command('emerge --oneshot --verbose kubeadm', $target, {
      _run_as => 'root',
    })
    if !($target in $control_plane_nodes) {
      run_command('kubeadm upgrade node --ignore-preflight-errors=SystemVerification --patches=/etc/kubernetes/patches', $target, {
        _run_as => 'root',
      })
    } else {
      run_plan('nest::kubernetes::reconcile_control_plane', {
        targets      => $target,
        etcd_servers => $etcd_servers,
      })
    }
    if $upgrade_kubelet {
      run_command('emerge --oneshot --verbose kubelet', $target, {
        _run_as => 'root',
      })
      run_command('systemctl restart kubelet', $target, {
        _run_as => 'root',
      })
    }
  }
}
