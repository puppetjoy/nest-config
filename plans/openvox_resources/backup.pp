# Backup OpenVox Puppet resources
#
# @param kubernetes_namespace Kubernetes namespace
# @param service Puppet service
# @param backup_service Backup directory name
plan nest::openvox_resources::backup (
  String $kubernetes_namespace = 'default',
  String $service              = 'puppet',
  String $backup_service       = $service,
) {
  $script = @("SCRIPT"/L)
    set -euo pipefail

    namespace=${kubernetes_namespace.shellquote}
    service=${service.shellquote}
    backup_service=${backup_service.shellquote}
    backup_dir="/nest/backup/${backup_service}"
    tmp_dir="${backup_dir}/.tmp"

    mkdir -p "${backup_dir}" "${tmp_dir}"

    primary=$(kubectl get pod -n "${namespace}" \
      -l "cnpg.io/cluster=${service}-cnpg,cnpg.io/instanceRole=primary" \
      -o jsonpath='{.items[0].metadata.name}')
    puppetserver=$(kubectl get pod -n "${namespace}" \
      -l "app.kubernetes.io/component=puppetserver,app.kubernetes.io/instance=${service}" \
      --sort-by=.metadata.creationTimestamp \
      -o jsonpath='{.items[-1].metadata.name}')
    container=$(kubectl get deploy -n "${namespace}" "${service}-puppetserver" \
      -o jsonpath='{.spec.template.spec.containers[0].name}')

    kubectl exec -n "${namespace}" "${primary}" -c postgres -- \
      pg_dump -U postgres -d openvoxdb --format=custom > "${tmp_dir}/puppetdb.dump"

    kubectl exec -n "${namespace}" "${puppetserver}" -c "${container}" -- \
      tar -C /etc/puppetlabs -cf - puppet/ssl puppetserver/ca \
      | zstd -T0 -19 -q > "${tmp_dir}/puppet-ssl.tar.zst"

    cat > "${tmp_dir}/metadata.json" <<EOF
    {
      "namespace": "${namespace}",
      "service": "${service}",
      "cnpg_primary": "${primary}",
      "puppetserver_pod": "${puppetserver}",
      "created_at": "$(date --iso-8601=seconds)"
    }
    EOF

    mv "${tmp_dir}/puppetdb.dump" "${backup_dir}/puppetdb.dump"
    mv "${tmp_dir}/puppet-ssl.tar.zst" "${backup_dir}/puppet-ssl.tar.zst"
    mv "${tmp_dir}/metadata.json" "${backup_dir}/metadata.json"
    rmdir "${tmp_dir}"

    ls -lh "${backup_dir}/puppetdb.dump" "${backup_dir}/puppet-ssl.tar.zst" "${backup_dir}/metadata.json"
    | SCRIPT

  run_command("bash -lc ${script.shellquote}", 'localhost', 'Backup OpenVox resources')
}
