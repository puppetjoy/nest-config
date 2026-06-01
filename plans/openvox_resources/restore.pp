# Restore OpenVox Puppet resources
#
# @param kubernetes_namespace Kubernetes namespace
# @param service Puppet service
# @param backup_service Backup directory name
# @param restore Safety gate
plan nest::openvox_resources::restore (
  String  $kubernetes_namespace = 'test',
  String  $service              = 'puppet',
  String  $backup_service       = $service,
  Boolean $restore              = false,
) {
  if $restore {
    $backup_dir   = "/nest/backup/${backup_service}"
    $restore_pod  = "${service}-openvox-restore"
    $cluster      = "${service}-cnpg"
    $puppetboard  = "${service}-puppetboard"
    $puppetdb     = "${service}-puppetdb"
    $puppetserver = "${service}-puppetserver"

    run_command("test -s ${backup_dir.shellquote}/puppetdb.dump && test -s ${backup_dir.shellquote}/puppet-ssl.tar.zst", 'localhost', 'Check OpenVox backup files')
    run_command("kubectl scale -n ${kubernetes_namespace.shellquote} deploy/${puppetboard.shellquote} deploy/${puppetdb.shellquote} deploy/${puppetserver.shellquote} --replicas=0", 'localhost', 'Scale OpenVox test consumers down')
    run_command("kubectl rollout status -n ${kubernetes_namespace.shellquote} deploy/${puppetboard.shellquote} --timeout=240s && kubectl rollout status -n ${kubernetes_namespace.shellquote} deploy/${puppetdb.shellquote} --timeout=240s && kubectl rollout status -n ${kubernetes_namespace.shellquote} deploy/${puppetserver.shellquote} --timeout=240s", 'localhost', 'Wait for OpenVox scale-down')
    run_command("kubectl delete pod -n ${kubernetes_namespace.shellquote} ${restore_pod.shellquote} --ignore-not-found=true --wait=true", 'localhost', 'Remove old restore pod')

    $restore_pod_yaml = @("YAML"/L)
      apiVersion: v1
      kind: Pod
      metadata:
        name: ${restore_pod}
        namespace: ${kubernetes_namespace}
      spec:
        restartPolicy: Never
        tolerations:
          - operator: Exists
        containers:
          - name: restore
            image: registry.eyrie/nest/stage1/server
            command: ['sleep', '3600']
            volumeMounts:
              - name: nest
                mountPath: /nest
              - name: puppet
                mountPath: /restore/etc/puppetlabs/puppet
              - name: puppetserver-ca
                mountPath: /restore/etc/puppetlabs/puppetserver/ca
        volumes:
          - name: nest
            hostPath:
              path: /nest
              type: Directory
          - name: puppet
            persistentVolumeClaim:
              claimName: ${service}-puppetserver-puppet-claim
          - name: puppetserver-ca
            persistentVolumeClaim:
              claimName: ${service}-puppetserver-ca-claim
      | YAML

    run_command("printf %s ${restore_pod_yaml.shellquote} | kubectl apply -f -", 'localhost', 'Create OpenVox restore pod')
    run_command("kubectl wait -n ${kubernetes_namespace.shellquote} --for=condition=Ready pod/${restore_pod.shellquote} --timeout=240s", 'localhost', 'Wait for OpenVox restore pod')
    run_command("kubectl exec -n ${kubernetes_namespace.shellquote} ${restore_pod.shellquote} -- bash -lc 'rm -rf /restore/etc/puppetlabs/puppet/ssl /restore/etc/puppetlabs/puppetserver/ca/* && mkdir -p /restore/etc/puppetlabs/puppet /restore/etc/puppetlabs/puppetserver/ca && zstd -dc ${backup_dir.shellquote}/puppet-ssl.tar.zst | tar -C /restore/etc/puppetlabs -xf -'", 'localhost', 'Restore Puppet SSL state')
    run_command("kubectl delete pod -n ${kubernetes_namespace.shellquote} ${restore_pod.shellquote} --wait=true", 'localhost', 'Remove OpenVox restore pod')

    $primary_pod = run_command([
      'kubectl', 'get', 'pod', '-n', $kubernetes_namespace,
      '-l', "cnpg.io/cluster=${cluster},cnpg.io/instanceRole=primary",
      '-o', 'jsonpath={.items[0].metadata.name}',
    ].shellquote, 'localhost', 'Find CNPG primary').first.value['stdout'].chomp

    run_command("kubectl exec -n ${kubernetes_namespace.shellquote} ${primary_pod.shellquote} -c postgres -- dropdb -U postgres --if-exists openvoxdb", 'localhost', 'Drop test PuppetDB database')
    run_command("kubectl exec -n ${kubernetes_namespace.shellquote} ${primary_pod.shellquote} -c postgres -- createdb -U postgres -O puppetdb openvoxdb", 'localhost', 'Create test PuppetDB database')
    run_command("kubectl exec -i -n ${kubernetes_namespace.shellquote} ${primary_pod.shellquote} -c postgres -- pg_restore -U postgres -d openvoxdb < ${backup_dir.shellquote}/puppetdb.dump", 'localhost', 'Restore PuppetDB dump')

    run_command("kubectl scale -n ${kubernetes_namespace.shellquote} deploy/${puppetserver.shellquote} deploy/${puppetdb.shellquote} deploy/${puppetboard.shellquote} --replicas=1", 'localhost', 'Scale OpenVox test consumers up')
    run_command("kubectl rollout status -n ${kubernetes_namespace.shellquote} deploy/${puppetserver.shellquote} --timeout=300s && kubectl rollout status -n ${kubernetes_namespace.shellquote} deploy/${puppetdb.shellquote} --timeout=300s && kubectl rollout status -n ${kubernetes_namespace.shellquote} deploy/${puppetboard.shellquote} --timeout=300s", 'localhost', 'Wait for OpenVox restore rollout')
  }
}
