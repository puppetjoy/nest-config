# Restore Eyrie Honcho resources
#
# @param namespace Kubernetes namespace
# @param service Honcho service
# @param service_name Kubernetes workload service name
# @param restore Safety gate
plan nest::eyrie::ai::honcho::restore (
  String  $namespace    = 'ai',
  String  $service      = 'honcho',
  String  $service_name = $service,
  Boolean $restore      = false,
) {
  if $restore {
    $backup_dir = "/nest/backup/${service_name}"
    $cluster    = "${service}-cnpg"
    $api        = "${service}-api"
    $deriver    = "${service}-deriver"
    $database   = 'honcho'
    $owner      = 'honcho'

    run_command("test -s ${backup_dir.shellquote}/honcho.dump", 'localhost', 'Check Honcho backup file')
    run_command("kubectl scale -n ${namespace.shellquote} deploy/${api.shellquote} deploy/${deriver.shellquote} --replicas=0", 'localhost', 'Scale Honcho consumers down')
    run_command("kubectl rollout status -n ${namespace.shellquote} deploy/${api.shellquote} --timeout=240s && kubectl rollout status -n ${namespace.shellquote} deploy/${deriver.shellquote} --timeout=240s", 'localhost', 'Wait for Honcho scale-down')

    $primary_pod = run_command([
      'kubectl', 'get', 'pod', '-n', $namespace,
      '-l', "cnpg.io/cluster=${cluster},cnpg.io/instanceRole=primary",
      '-o', 'jsonpath={.items[0].metadata.name}',
    ].shellquote, 'localhost', 'Find CNPG primary').first.value['stdout'].chomp

    run_command("kubectl exec -n ${namespace.shellquote} ${primary_pod.shellquote} -c postgres -- dropdb -U postgres --if-exists --force ${database.shellquote}", 'localhost', 'Drop Honcho database')
    run_command("kubectl exec -n ${namespace.shellquote} ${primary_pod.shellquote} -c postgres -- createdb -U postgres -O ${owner.shellquote} ${database.shellquote}", 'localhost', 'Create Honcho database')
    run_command("kubectl exec -n ${namespace.shellquote} ${primary_pod.shellquote} -c postgres -- psql -U postgres -d ${database.shellquote} -c 'CREATE EXTENSION IF NOT EXISTS vector'", 'localhost', 'Ensure pgvector extension')
    run_command("kubectl exec -i -n ${namespace.shellquote} ${primary_pod.shellquote} -c postgres -- pg_restore -U postgres -d ${database.shellquote} < ${backup_dir.shellquote}/honcho.dump", 'localhost', 'Restore Honcho dump')

    run_command("kubectl scale -n ${namespace.shellquote} deploy/${api.shellquote} deploy/${deriver.shellquote} --replicas=1", 'localhost', 'Scale Honcho consumers up')
    run_command("kubectl rollout status -n ${namespace.shellquote} deploy/${api.shellquote} --timeout=300s && kubectl rollout status -n ${namespace.shellquote} deploy/${deriver.shellquote} --timeout=300s", 'localhost', 'Wait for Honcho restore rollout')
  }
}
