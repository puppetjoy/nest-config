# Configure Ceph
#
# @param rook Deploy Rook
# @param csi Deploy Ceph CSI drivers
# @param ceph Deploy Ceph
plan nest::kubernetes::deploy_ceph ( # lint:ignore:deploy_plan_boundary -- existing Ceph workaround commands need migration into chart resources
  Boolean $rook = true,
  Boolean $csi  = true,
  Boolean $ceph = true,
) {
  run_plan('nest::kubernetes::deploy', {
    'service'   => 'rook',
    'app'       => 'rook-ceph',
    'chart'     => 'rook-release/rook-ceph',
    'namespace' => 'rook-ceph',
    'repo_url'  => 'https://charts.rook.io/release',
    'version'   => '1.20.0',
    'wait'      => true,
    'deploy'    => $rook,
  })

  run_plan('nest::kubernetes::deploy', {
    'service'   => 'ceph-csi-drivers',
    'app'       => 'ceph-csi-drivers',
    'chart'     => 'ceph-csi-operator/ceph-csi-drivers',
    'namespace' => 'rook-ceph',
    'repo_url'  => 'https://ceph.github.io/ceph-csi-operator',
    'version'   => '1.0.1',
    'wait'      => true,
    'deploy'    => $csi,
  })

  run_plan('nest::kubernetes::deploy', {
    'service'   => 'ceph',
    'app'       => 'rook-ceph-cluster',
    'chart'     => 'rook-release/rook-ceph-cluster',
    'namespace' => 'rook-ceph',
    'repo_url'  => 'https://charts.rook.io/release',
    'version'   => '1.20.0',
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
