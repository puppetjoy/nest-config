# Remove and reset Kubernetes nodes
#
# @param targets Nodes to remove
#
# @see https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/#tear-down
plan nest::kubernetes::remove_node (
  TargetSpec $targets,
  Boolean    $drain = true,
) {
  $members = get_targets($targets).reduce([]) |$memo, $node| {
    $result = run_command("kubectl get node ${node.name}", 'localhost', "Check if ${node.name} is a cluster member", {
      _catch_errors => true,
    })

    if $result.ok {
      $memo << $node
    } else {
      $memo
    }
  }

  if $drain {
    run_plan('nest::kubernetes::drain_node', $members, _description => 'Drain nodes')
  }

  run_command('kubeadm reset --force', $targets, 'Reset node', {
    _run_as => 'root',
  })

  $members.each |$node| {
    run_command("kubectl delete node ${node.name}", 'localhost', "Delete node ${node.name} from the cluster")
  }
}
