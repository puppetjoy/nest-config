# Generate kube-vip static pod manifest
#
# @param targets Nodes to generate config on
# @param vip Virtual IP address to advertise
#
# @see https://kube-vip.io/docs/installation/static/
plan nest::kubernetes::generate_kube_vip_manifest (
  TargetSpec              $targets,
  Stdlib::IP::Address::V4 $vip,
  String                  $version = 'v1.0.2',
) {
  parallelize(get_targets($targets)) |$t| {
    # XXX Generalize this
    $bgp_peers = $t.name ? {
      'control1' => ['172.22.4.8', '172.22.4.9'],
      'control2' => ['172.22.4.7', '172.22.4.9'],
      'control3' => ['172.22.4.7', '172.22.4.8'],
      default    => fail("Can't determine BGP peers for ${t.name}")
    }

    $kube_vip_cmd_quoted = [
      '/usr/bin/podman', 'run', '--network', 'host', '--rm', "ghcr.io/kube-vip/kube-vip:${version}",
      'manifest', 'pod',
      '--interface', 'lo',
      '--address', $vip,
      '--controlplane',
      '--bgp',
      '--localAS', '65000',
      '--bgppeers', $bgp_peers.map |$p| { "${p}:65000::false" }.join(','),
    ].flatten.shellquote

    $kube_vip_cmd = "${kube_vip_cmd_quoted} --bgpRouterID \$(facter networking.ip) > /etc/kubernetes/manifests/kube-vip.yaml"

    run_command($kube_vip_cmd, $t, 'Generate kube-vip pod manifest', {
      _run_as => 'root',
    })
  }
}
