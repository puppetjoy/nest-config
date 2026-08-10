# Initialize Kubernetes control plane nodes
#
# @param targets Hosts to initialize as the control plane
# @param name Name of the cluster to configure
# @param control_plane_endpoint Address control plane is reachable on
# @param etcd_servers Explicit etcd endpoints for API servers
# @param vip_advertisers Control-plane members allowed to advertise the API VIP
plan nest::kubernetes::init (
  TargetSpec              $targets,
  String                  $name,
  String                  $control_plane_endpoint,
  Stdlib::IP::Address::V4 $vip,
  Array[String]           $etcd_servers    = [],
  Array[String]           $vip_advertisers = [],
) {
  $nodes      = get_targets($targets)
  $node_names = $nodes.map |$node| { $node.name }
  $init_node  = $nodes[0]
  $join_nodes = $nodes - $init_node

  if $vip_advertisers.empty {
    $vip_nodes = $nodes
  } else {
    $vip_nodes = $nodes.filter |$node| { $node.name in $vip_advertisers }
    if $vip_nodes.length != $vip_advertisers.length {
      fail("vip_advertisers must contain unique members from ${node_names.join(', ')}; got ${vip_advertisers.join(', ')}")
    }
    if $vip_nodes.length < 2 {
      fail('vip_advertisers must retain at least two control-plane members')
    }
  }
  $excluded_vip_nodes = $nodes - $vip_nodes

  run_command('systemctl start crio', $nodes, 'Start CRI-O', {
    _run_as => 'root',
  })

  run_command('systemctl stop kubelet', $nodes, 'Stop kubelet', {
    _run_as => 'root',
  })

  $kubeadm_cert_key_cmd = 'kubeadm certs certificate-key'
  $cert_key = Sensitive(run_command($kubeadm_cert_key_cmd, $init_node, 'Generate kubeadm certificate key', {
    _run_as => 'root',
  }).first.value['stdout'].chomp)

  $kubeadm_config = epp('nest/kubernetes/kubeadm-init-config.yaml.epp', {
    cluster_name           => $name,
    control_plane_endpoint => $control_plane_endpoint,
    certificate_key        => $cert_key,
    # Fresh bootstrap must use the init node's available local etcd member.
    # The final read endpoint set is reconciled only after every peer joins.
    etcd_servers           => [],
  })
  write_file($kubeadm_config, '/root/kubeadm-config.yaml', $nodes, {
    _run_as => 'root',
  })

  run_plan('nest::kubernetes::generate_kube_vip_manifest', {
    targets => $init_node,
    vip     => $vip,
  })

  $kubeadm_init_cmd = @(CMD/L)
    kubeadm init \
    --config=/root/kubeadm-config.yaml \
    --upload-certs
    | CMD
  run_command($kubeadm_init_cmd , $init_node, 'Initialize first control plane node', {
    _run_as => 'root',
  })

  # Wait for control plane to settle
  ctrl::sleep(30)

  $kubeadm_token_cmd = 'kubeadm token create --print-join-command'
  $kubeadm_join_cmd = run_command($kubeadm_token_cmd, $init_node, 'Get kubeadm join command', {
    _run_as => 'root',
  }).first.value['stdout'].chomp

  $full_kubeadm_join_cmd = "${kubeadm_join_cmd} --control-plane --certificate-key ${cert_key.unwrap}"
  run_command($full_kubeadm_join_cmd, $join_nodes, 'Join control plane', {
    _run_as => 'root',
  })

  if !$etcd_servers.empty {
    $nodes.each |$node| {
      run_plan('nest::kubernetes::reconcile_control_plane', {
        targets      => $node,
        etcd_servers => $etcd_servers,
      })
    }
  }

  run_plan('nest::kubernetes::generate_kube_vip_manifest', {
    targets => $join_nodes,
    vip     => $vip,
  })

  $vip_pods = $vip_nodes.map |$node| { "pod/kube-vip-${node.name}" }
  $wait_vip_pods_command = [
    'kubectl', '--kubeconfig=/etc/kubernetes/admin.conf', '-n', 'kube-system',
    'wait', '--for=condition=Ready',
  ] + $vip_pods + ['--timeout=180s']
  $vip_ready_command = [
    'kubectl', '--kubeconfig=/etc/kubernetes/admin.conf',
    # Use the DNS control-plane endpoint so TLS verifies the kubeadm-managed
    # certificate while DNS still resolves the request through the VIP.
    "--server=https://${control_plane_endpoint}:6443", 'get', '--raw=/readyz?verbose',
  ].shellquote
  run_command($wait_vip_pods_command.shellquote, $init_node, 'Require intended kube-vip mirror Pods before withdrawal', {
    _run_as => 'root',
  })
  $vip_nodes.each |$node| {
    $observer = ($nodes - $node)[0]
    $route_command = [
      'birdc', 'show', 'route', 'for', "${vip}/32", 'protocol', $node.name,
    ].shellquote
    run_command("${route_command} | grep -F -- ${("${vip}/32").shellquote}", $observer, "Require ${node.name} kube-vip BGP route from peer observer ${observer.name}", {
      _run_as => 'root',
    })
  }
  run_command($vip_ready_command, $init_node, 'Require API VIP readiness before advertiser withdrawal', {
    _run_as => 'root',
  })

  if !$excluded_vip_nodes.empty {
    $withdrawal = catch_errors() || {
      $excluded_vip_nodes.each |$excluded_node| {
        run_plan('nest::kubernetes::generate_kube_vip_manifest', {
          targets   => $excluded_node,
          vip       => $vip,
          advertise => false,
        })
        run_command("kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system wait --for=delete pod/kube-vip-${excluded_node.name} --timeout=180s", $init_node, "Wait for kube-vip withdrawal from ${excluded_node.name}", {
          _run_as => 'root',
        })
        $excluded_route_command = [
          'birdc', 'show', 'route', 'for', "${vip}/32", 'protocol', $excluded_node.name,
        ].shellquote
        $excluded_route_observer = ($nodes - $excluded_node)[0]
        $withdrawn_route_template = @(SCRIPT/L)
          while :; do
            route="$(__ROUTE__)" || exit 1
            if ! printf '%s\n' "$route" | grep -F -- __VIP__; then
              break
            fi
            sleep 2
          done
          | SCRIPT
        $withdrawn_route_script = $withdrawn_route_template
          .regsubst('__ROUTE__', $excluded_route_command, 'G')
          .regsubst('__VIP__', ("${vip}/32").shellquote, 'G')
        $wait_withdrawn_route_command = ['timeout', '180', 'sh', '-c', $withdrawn_route_script].shellquote
        run_command($wait_withdrawn_route_command, $excluded_route_observer, "Wait for kube-vip BGP route withdrawal from ${excluded_node.name} on peer observer ${excluded_route_observer.name}", {
          _run_as => 'root',
        })
        run_command($wait_vip_pods_command.shellquote, $init_node, 'Recheck intended kube-vip mirror Pods after withdrawal', {
          _run_as => 'root',
        })
        $vip_nodes.each |$vip_node| {
          $route_observer = ($nodes - $vip_node)[0]
          $route_command = [
            'birdc', 'show', 'route', 'for', "${vip}/32", 'protocol', $vip_node.name,
          ].shellquote
          run_command("${route_command} | grep -F -- ${("${vip}/32").shellquote}", $route_observer, "Recheck ${vip_node.name} kube-vip BGP route from peer observer ${route_observer.name}", {
            _run_as => 'root',
          })
        }
        run_command($vip_ready_command, $init_node, 'Require API VIP continuity after advertiser withdrawal', {
          _run_as => 'root',
        })
      }
    }

    if $withdrawal =~ Error {
      warning("kube-vip advertiser withdrawal failed; re-advertising excluded members: ${withdrawal.message}")
      $rollback = catch_errors() || {
        run_plan('nest::kubernetes::generate_kube_vip_manifest', {
          targets => $excluded_vip_nodes,
          vip     => $vip,
        })
        $all_vip_pods = $nodes.map |$node| { "pod/kube-vip-${node.name}" }
        $wait_all_vip_pods_command = [
          'kubectl', '--kubeconfig=/etc/kubernetes/admin.conf', '-n', 'kube-system',
          'wait', '--for=condition=Ready',
        ] + $all_vip_pods + ['--timeout=180s']
        run_command($wait_all_vip_pods_command.shellquote, $init_node, 'Wait for kube-vip re-advertisement rollback', {
          _run_as => 'root',
        })
        $nodes.each |$rollback_node| {
          $rollback_observer = ($nodes - $rollback_node)[0]
          $rollback_route_command = [
            'birdc', 'show', 'route', 'for', "${vip}/32", 'protocol', $rollback_node.name,
          ].shellquote
          run_command("${rollback_route_command} | grep -F -- ${("${vip}/32").shellquote}", $rollback_observer, "Require ${rollback_node.name} kube-vip BGP route after rollback from peer observer ${rollback_observer.name}", {
            _run_as => 'root',
          })
        }
        run_command($vip_ready_command, $init_node, 'Require API VIP readiness after re-advertisement rollback', {
          _run_as => 'root',
        })
      }
      if $rollback =~ Error {
        fail_plan("kube-vip withdrawal failed (${withdrawal.message}) and re-advertisement rollback failed (${rollback.message})", 'nest/kubernetes-kube-vip-rollback-failed')
      }
      fail_plan("kube-vip withdrawal failed and excluded members were safely re-advertised: ${withdrawal.message}", 'nest/kubernetes-kube-vip-withdrawal-rolled-back')
    }
  }

  run_command('rm -f /root/kubeadm-config.yaml', $nodes, 'Remove kubeadm config file', {
    _run_as => 'root',
  })

  $kubeconfig_dest     = "/nest/home/kubeconfigs/${name}.conf"
  $copy_kubeconfig_cmd = "cp /etc/kubernetes/admin.conf ${kubeconfig_dest} && chown joy ${kubeconfig_dest}"
  run_command($copy_kubeconfig_cmd, $init_node, 'Copy kubeconfig to Nest home', {
    _run_as => 'root',
  })

  # Wait for control plane to settle
  ctrl::sleep(30)

  # Configure CoreDNS to forward requests to Nest nameserver. CoreDNS won't
  # start without the Calico pod network so updating this config before Calico
  # deploys guarantees CoreDNS will launch with the right config the first time.
  run_plan('nest::kubernetes::replace', {
    manifest => 'nest/kubernetes/coredns-config.yaml',
  })
}
