# Uncordon a Kubernetes node
#
# @param $targets Nodes to uncordon
plan nest::kubernetes::uncordon_node (
  TargetSpec $targets,
) {
  get_targets($targets).each |$node| {
    run_command("kubectl uncordon ${node.name}", 'localhost', "Uncordon ${node.name}")
  }
}
