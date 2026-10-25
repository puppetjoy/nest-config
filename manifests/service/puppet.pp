class nest::service::puppet (
  Optional[Sensitive] $puppetboard_secret_key = undef,
  Optional[Sensitive] $r10k_deploy_key        = undef,
  Optional[Hash]      $compiler_release       = undef,
) {
  if defined(Class['nest::kubernetes']) {
    $compiler_patch = $compiler_release ? {
      undef   => [{ 'op' => 'test', 'path' => '/kind', 'value' => 'Deployment' }],
      default => nest::openvox_compiler_patches($compiler_release, $nest::kubernetes::service)[0]['patch'],
    }
    $compiler_patch_yaml = $compiler_patch.stdlib::to_yaml
    $puppetboard_secret_key_base64 = $puppetboard_secret_key ? {
      undef   => '',
      default => base64('encode', $puppetboard_secret_key.unwrap),
    }
    $r10k_deploy_key_base64 = $r10k_deploy_key ? {
      undef   => '',
      default => base64('encode', $r10k_deploy_key.unwrap),
    }
    $r10k_known_hosts             = lookup('nest::ssh_host_keys').map |$hosts, $key| { "${hosts} ${key}" }.join("\n")
    $r10k_known_hosts_base64      = base64('encode', $r10k_known_hosts)
  } else {
    fail('The Podman Puppet runtime is retired; use the Kubernetes OpenVox service')
  }
}
