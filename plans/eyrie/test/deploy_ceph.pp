# Deploy test Ceph
#
# @param deploy Run or skip the deployment
# @param render_to Just render the template
plan nest::eyrie::test::deploy_ceph (
  Boolean $deploy    = true,
  String  $render_to = '',
) {
  run_plan('nest::kubernetes::deploy', {
    'service'   => 'ceph',
    'app'       => 'rook-ceph-cluster',
    'chart'     => 'rook-release/rook-ceph-cluster',
    'namespace' => 'test',
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
    'deploy'    => $deploy,
    'render_to' => $render_to,
  })

  if $deploy and $render_to == '' {
    # Workaround RGW dashboard connection issue on IPVS cluster
    # See: https://gitlab.james.tl/nest/config/-/issues/66
    run_command('kubectl wait --for=condition=ready -n test cephclusters/ceph-test --timeout=3600s', 'localhost', 'Wait for cluster to be ready')
    run_command('kubectl delete pod -n test -l app=rook-ceph-tools', 'localhost', 'Restart Ceph toolbox')
    run_command('kubectl exec -n test deployments/rook-ceph-tools -- ceph config set global rgw_dns_name rook-ceph-rgw-ceph-test-objectstore.test.svc', 'localhost', 'Configure RGW DNS name')
  }
}
