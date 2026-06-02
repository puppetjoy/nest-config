# Backup Eyrie OpenVox Puppet resources
#
# @param namespace Kubernetes namespace
# @param service Puppet service
# @param service_name Kubernetes workload service name
plan nest::eyrie::openvox::backup (
  String $namespace    = 'default',
  String $service      = 'puppet',
  String $service_name = $service,
) {
  $backup_dir   = "/nest/backup/${service_name}"
  $tmp_dir      = "${backup_dir}/.tmp"
  $cluster      = "${service}-cnpg"
  $puppetserver = "${service}-puppetserver"

  run_command("mkdir -p ${backup_dir.shellquote} ${tmp_dir.shellquote}", 'localhost', 'Create backup directory')

  $primary_pod = run_command([
    'kubectl', 'get', 'pod', '-n', $namespace,
    '-l', "cnpg.io/cluster=${cluster},cnpg.io/instanceRole=primary",
    '-o', 'jsonpath={.items[0].metadata.name}',
  ].shellquote, 'localhost', 'Find CNPG primary').first.value['stdout'].chomp

  $puppetserver_pod = run_command([
    'kubectl', 'get', 'pod', '-n', $namespace,
    '-l', "app.kubernetes.io/component=puppetserver,app.kubernetes.io/instance=${service}",
    '--sort-by=.metadata.creationTimestamp',
    '-o', 'jsonpath={.items[-1].metadata.name}',
  ].shellquote, 'localhost', 'Find Puppetserver pod').first.value['stdout'].chomp

  $container = run_command([
    'kubectl', 'get', 'deploy', '-n', $namespace, $puppetserver,
    '-o', 'jsonpath={.spec.template.spec.containers[0].name}',
  ].shellquote, 'localhost', 'Find Puppetserver container').first.value['stdout'].chomp

  run_command("kubectl exec -n ${namespace.shellquote} ${primary_pod.shellquote} -c postgres -- pg_dump -U postgres -d openvoxdb --format=custom > ${tmp_dir.shellquote}/puppetdb.dump", 'localhost', 'Dump PuppetDB')
  run_command("kubectl exec -n ${namespace.shellquote} ${puppetserver_pod.shellquote} -c ${container.shellquote} -- tar -C /etc/puppetlabs -cf - puppet/ssl puppetserver/ca | zstd -T0 -19 -q > ${tmp_dir.shellquote}/puppet-ssl.tar.zst", 'localhost', 'Archive Puppet SSL state')

  $metadata = @("JSON"/L)
    {
      "namespace": "${namespace}",
      "service": "${service}",
      "cnpg_primary": "${primary_pod}",
      "puppetserver_pod": "${puppetserver_pod}",
      "created_at": "$(date --iso-8601=seconds)"
    }
    | JSON

  run_command("cat > ${tmp_dir.shellquote}/metadata.json <<'EOF'\n${metadata}\nEOF", 'localhost', 'Write backup metadata')
  run_command("mv ${tmp_dir.shellquote}/puppetdb.dump ${backup_dir.shellquote}/puppetdb.dump && mv ${tmp_dir.shellquote}/puppet-ssl.tar.zst ${backup_dir.shellquote}/puppet-ssl.tar.zst && mv ${tmp_dir.shellquote}/metadata.json ${backup_dir.shellquote}/metadata.json && rmdir ${tmp_dir.shellquote}", 'localhost', 'Publish backup')
  run_command("ls -lh ${backup_dir.shellquote}/puppetdb.dump ${backup_dir.shellquote}/puppet-ssl.tar.zst ${backup_dir.shellquote}/metadata.json", 'localhost', 'List backup files')
}
