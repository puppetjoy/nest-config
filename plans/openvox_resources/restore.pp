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
    $script = @("SCRIPT"/L)
      set -euo pipefail

      namespace=${kubernetes_namespace.shellquote}
      service=${service.shellquote}
      backup_service=${backup_service.shellquote}
      backup_dir="/nest/backup/${backup_service}"
      restore_pod="${service}-openvox-restore"

      test -s "${backup_dir}/puppetdb.dump"
      test -s "${backup_dir}/puppet-ssl.tar.zst"

      kubectl scale -n "${namespace}" \
        deploy/${service}-puppetboard \
        deploy/${service}-puppetdb \
        deploy/${service}-puppetserver \
        --replicas=0
      kubectl rollout status -n "${namespace}" "deploy/${service}-puppetboard" --timeout=240s
      kubectl rollout status -n "${namespace}" "deploy/${service}-puppetdb" --timeout=240s
      kubectl rollout status -n "${namespace}" "deploy/${service}-puppetserver" --timeout=240s

      kubectl delete pod -n "${namespace}" "${restore_pod}" --ignore-not-found=true --wait=true
      cat <<EOF | kubectl apply -f -
      apiVersion: v1
      kind: Pod
      metadata:
        name: ${restore_pod}
        namespace: ${namespace}
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
      EOF
      trap 'kubectl delete pod -n "${namespace}" "${restore_pod}" --ignore-not-found=true --wait=false >/dev/null 2>&1 || true' EXIT
      kubectl wait -n "${namespace}" --for=condition=Ready "pod/${restore_pod}" --timeout=240s

      kubectl exec -n "${namespace}" "${restore_pod}" -- bash -lc \
        "rm -rf /restore/etc/puppetlabs/puppet/ssl /restore/etc/puppetlabs/puppetserver/ca/* && \
         mkdir -p /restore/etc/puppetlabs/puppet /restore/etc/puppetlabs/puppetserver/ca && \
         zstd -dc /nest/backup/${backup_service}/puppet-ssl.tar.zst | \
           tar -C /restore/etc/puppetlabs -xf -"

      primary=$(kubectl get pod -n "${namespace}" \
        -l "cnpg.io/cluster=${service}-cnpg,cnpg.io/instanceRole=primary" \
        -o jsonpath='{.items[0].metadata.name}')
      kubectl exec -n "${namespace}" "${primary}" -c postgres -- \
        dropdb -U postgres --if-exists openvoxdb
      kubectl exec -n "${namespace}" "${primary}" -c postgres -- \
        createdb -U postgres -O puppetdb openvoxdb
      kubectl exec -i -n "${namespace}" "${primary}" -c postgres -- \
        pg_restore -U postgres -d openvoxdb < "${backup_dir}/puppetdb.dump"

      kubectl scale -n "${namespace}" \
        deploy/${service}-puppetserver \
        deploy/${service}-puppetdb \
        deploy/${service}-puppetboard \
        --replicas=1
      kubectl rollout status -n "${namespace}" "deploy/${service}-puppetserver" --timeout=300s
      kubectl rollout status -n "${namespace}" "deploy/${service}-puppetdb" --timeout=300s
      kubectl rollout status -n "${namespace}" "deploy/${service}-puppetboard" --timeout=300s
    | SCRIPT

    run_command("bash -lc ${script.shellquote}", 'localhost', 'Restore OpenVox resources')
  }
}
