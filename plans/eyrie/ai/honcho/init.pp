# Initialize Eyrie Honcho resources from backup
#
# @param namespace Kubernetes namespace
# @param service Honcho service
# @param service_name Kubernetes workload service name
plan nest::eyrie::ai::honcho::init (
  String $namespace    = 'ai',
  String $service      = 'honcho',
  String $service_name = $service,
) {
  $cluster = "${service}-cnpg"
  $api     = "${service}-api"
  $deriver = "${service}-deriver"

  run_command("kubectl wait -n ${namespace.shellquote} --for=condition=Available deploy/${api.shellquote} deploy/${deriver.shellquote} --timeout=600s", 'localhost', 'Wait for Honcho deployments')
  run_command("kubectl wait -n ${namespace.shellquote} --for=condition=Ready cluster/${cluster.shellquote} --timeout=600s", 'localhost', 'Wait for Honcho CNPG cluster')
  run_plan('nest::eyrie::ai::honcho::restore', {
    'namespace'    => $namespace,
    'service'      => $service,
    'service_name' => $service_name,
    'restore'      => true,
  })
}
