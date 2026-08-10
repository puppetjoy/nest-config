# Generate kube-vip static pod manifest
#
# @param targets Nodes to generate config on
# @param vip Virtual IP address to advertise
# @param advertise Whether the targets should advertise the control-plane VIP
#
# @see https://kube-vip.io/docs/installation/static/
plan nest::kubernetes::generate_kube_vip_manifest (
  TargetSpec              $targets,
  Stdlib::IP::Address::V4 $vip,
  String                  $version   = 'v1.0.2',
  Boolean                 $advertise = true,
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

    $render_command = @(COMMAND/L)
      set -eu
      manifest=/etc/kubernetes/manifests/kube-vip.yaml
      temporary="$(mktemp /etc/kubernetes/manifests/.kube-vip.XXXXXX.yaml)"
      trap 'rm -f "$temporary"' EXIT
      __KUBE_VIP__ --bgpRouterID "$(facter networking.ip)" > "$temporary"
      test -s "$temporary"
      chmod 0600 "$temporary"
      mv -f "$temporary" "$manifest"
      | COMMAND
    $kube_vip_cmd = $render_command.regsubst('__KUBE_VIP__', $kube_vip_cmd_quoted, 'G')

    if $advertise {
      run_command($kube_vip_cmd, $t, 'Generate kube-vip pod manifest', {
        _run_as => 'root',
      })
    } else {
      $remove_command = @(COMMAND/L)
        set -eu
        manifest=/etc/kubernetes/manifests/kube-vip.yaml
        if [ -e "$manifest" ]; then
          backup_dir=/root/kubernetes-manifest-backups
          install -d -m 0700 "$backup_dir"
          timestamp="$(date -u +%Y%m%dT%H%M%S.%N)"
          install -m 0600 "$manifest" "$backup_dir/kube-vip-${timestamp}.yaml"
          rm "$manifest"
        fi
        | COMMAND
      run_command($remove_command, $t, 'Stop advertising kube-vip from excluded member', {
        _run_as => 'root',
      })
    }
  }
}
