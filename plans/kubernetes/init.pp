# Initialize Kubernetes control plane nodes
#
# @param targets Hosts to initialize as the control plane
# @param name Name of the cluster to configure
# @param control_plane_endpoint Address control plane is reachable on
plan nest::kubernetes::init (
  TargetSpec              $targets,
  String                  $name,
  String                  $control_plane_endpoint,
  Stdlib::IP::Address::V4 $vip,
) {
  $nodes = get_targets($targets)
  $init_node = $nodes[0]
  $join_nodes = $nodes - $init_node

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
  })
  write_file($kubeadm_config, '/root/kubeadm-config.yaml', $nodes, {
    _run_as => 'root',
  })

  run_plan('nest::kubernetes::generate_kube_vip_manifest', {
    targets => $init_node,
    vip     => $vip,
  })

  $kubeadm_init_cmd = @(CMD/L)
    kubeadm init --config=/root/kubeadm-config.yaml \
    --ignore-preflight-errors=Swap,FileContent--proc-sys-net-bridge-bridge-nf-call-iptables \
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

  run_plan('nest::kubernetes::generate_kube_vip_manifest', {
    targets => $join_nodes,
    vip     => $vip,
  })

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
