# Drain a Kubernetes node
#
# @param $targets Nodes to drain
plan nest::kubernetes::drain_node (
  TargetSpec $targets,
) {
  get_targets($targets).each |$node| {
    run_command("kubectl drain ${node.name} --delete-emptydir-data --force --ignore-daemonsets", 'localhost', "Drain ${node.name}")
  }
}
