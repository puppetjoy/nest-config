# Backup Eyrie Honcho resources
#
# @param namespace Kubernetes namespace
# @param service Honcho service
# @param service_name Kubernetes workload service name
plan nest::eyrie::ai::honcho::backup (
  String $namespace    = 'ai',
  String $service      = 'honcho',
  String $service_name = $service,
) {
  $backup_dir = "/nest/backup/${service_name}"
  $tmp_dir    = "${backup_dir}/.tmp"
  $cluster    = "${service}-cnpg"
  $database   = 'honcho'

  run_command("mkdir -p ${backup_dir.shellquote} ${tmp_dir.shellquote}", 'localhost', 'Create backup directory')

  $primary_pod = run_command([
    'kubectl', 'get', 'pod', '-n', $namespace,
    '-l', "cnpg.io/cluster=${cluster},cnpg.io/instanceRole=primary",
    '-o', 'jsonpath={.items[0].metadata.name}',
  ].shellquote, 'localhost', 'Find CNPG primary').first.value['stdout'].chomp

  run_command("kubectl exec -n ${namespace.shellquote} ${primary_pod.shellquote} -c postgres -- pg_dump -U postgres -d ${database.shellquote} --format=custom > ${tmp_dir.shellquote}/honcho.dump", 'localhost', 'Dump Honcho database')

  $created_at = run_command('date --iso-8601=seconds', 'localhost', 'Timestamp backup').first.value['stdout'].chomp
  $metadata = @("JSON"/L)
    {
      "namespace": "${namespace}",
      "service": "${service}",
      "cnpg_primary": "${primary_pod}",
      "created_at": "${created_at}"
    }
    | JSON

  run_command("cat > ${tmp_dir.shellquote}/metadata.json <<'EOF'\n${metadata}\nEOF", 'localhost', 'Write backup metadata')
  run_command("mv ${tmp_dir.shellquote}/honcho.dump ${backup_dir.shellquote}/honcho.dump && mv ${tmp_dir.shellquote}/metadata.json ${backup_dir.shellquote}/metadata.json && rmdir ${tmp_dir.shellquote}", 'localhost', 'Publish backup')
  run_command("ls -lh ${backup_dir.shellquote}/honcho.dump ${backup_dir.shellquote}/metadata.json", 'localhost', 'List backup files')
}
