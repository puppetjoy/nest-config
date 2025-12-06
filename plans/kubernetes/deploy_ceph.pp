# Configure Ceph
#
# @param rook Deploy Rook
# @param ceph Deploy Ceph
plan nest::kubernetes::deploy_ceph (
  Boolean $rook = true,
  Boolean $ceph = true,
) {
  run_plan('nest::kubernetes::deploy', {
    'service'   => 'rook',
    'app'       => 'rook-ceph',
    'chart'     => 'rook-release/rook-ceph',
    'namespace' => 'rook-ceph',
    'repo_url'  => 'https://charts.rook.io/release',
    'version'   => '1.18.7',
    'wait'      => true,
    'deploy'    => $rook,
  })

  run_plan('nest::kubernetes::deploy', {
    'service'   => 'ceph',
    'app'       => 'rook-ceph-cluster',
    'chart'     => 'rook-release/rook-ceph-cluster',
    'namespace' => 'rook-ceph',
    'repo_url'  => 'https://charts.rook.io/release',
    'version'   => '1.18.7',
    'subcharts' => [
      {
        'service'  => 'ceph-monitoring',
        'app'      => 'kube-prometheus-stack',
        'chart'    => 'prometheus-community/kube-prometheus-stack',
        'repo_url' => 'https://prometheus-community.github.io/helm-charts',
        'version'  => '79.7.1',
      },
    ],
    'deploy'    => $ceph,
  })

  if $ceph {
    # Workaround RGW dashboard connection issue on IPVS cluster
    # See: https://gitlab.joyfullee.me/nest/config/-/issues/66
    run_command('kubectl wait --for=condition=ready -n rook-ceph cephclusters/ceph --timeout=3600s', 'localhost', 'Wait for cluster to be ready')
    run_command('kubectl delete pod -n rook-ceph -l app=rook-ceph-tools', 'localhost', 'Restart Ceph toolbox')
    run_command('kubectl exec -n rook-ceph deployments/rook-ceph-tools -- ceph config set global rgw_dns_name rook-ceph-rgw-ceph-objectstore.rook-ceph.svc', 'localhost', 'Configure RGW DNS name')

    # Workaround dashboard initialization issue
    # See: https://gitlab.joyfullee.me/nest/config/-/issues/65
    run_command('kubectl delete pod -n rook-ceph -l app=rook-ceph-operator', 'localhost', 'Restart Rook operator')
  }
}
