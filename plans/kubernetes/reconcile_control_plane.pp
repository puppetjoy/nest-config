# Reconcile one kubeadm control-plane member through the live ClusterConfiguration
#
# Run this plan once per member. It refuses multi-target execution, acquires a
# cluster-visible lock, and gates mutation on API readiness plus exact etcd
# topology and applied-index synchronization. Any failure after mutation
# attempts ConfigMap and local static-manifest restoration independently.
#
# @param targets Exactly one control-plane node to reconcile
# @param etcd_servers Ordered etcd client endpoints for kube-apiserver
# @param etcd_member_names Exact voting etcd member names required by the gate
plan nest::kubernetes::reconcile_control_plane (
  TargetSpec    $targets,
  Array[String] $etcd_servers,
  Array[String] $etcd_member_names = ['control1', 'control2', 'control3'],
) {
  $members = get_targets($targets)
  if $members.length != 1 {
    fail('reconcile_control_plane requires exactly one target')
  }

  $member              = $members[0]
  $member_name         = $member.name
  $endpoint_csv        = $etcd_servers.join(',')
  $patches             = '/etc/kubernetes/patches'
  $manifest            = '/etc/kubernetes/manifests/kube-apiserver.yaml'
  $lock_name           = 'nest-control-plane-reconcile-lock'
  $member_names_string = $etcd_member_names.shellquote
  $member_name_quoted  = $member_name.shellquote
  $endpoint_csv_quoted = $endpoint_csv.shellquote
  $patches_quoted      = $patches.shellquote
  $manifest_quoted     = $manifest.shellquote
  $lock_name_quoted    = $lock_name.shellquote
  $etcd_arg_quoted     = "--etcd-servers=${endpoint_csv}".shellquote

  $ready_command = [
    'kubectl', 'get', '--raw=/readyz?verbose',
  ].shellquote
  $read_config_command = [
    'kubectl', '--kubeconfig=/etc/kubernetes/admin.conf', '-n', 'kube-system',
    'get', 'configmap', 'kubeadm-config',
    '--output=jsonpath={.data.ClusterConfiguration}',
  ].shellquote
  $rewrite_command = [
    '/usr/local/sbin/reconcile-kubeadm-cluster-config',
  ] + $etcd_servers
  $check_command = [
    '/usr/local/sbin/reconcile-kubeadm-cluster-config', '--check',
  ] + $etcd_servers
  $rewrite_command_string = $rewrite_command.shellquote
  $check_command_string   = $check_command.shellquote
  $get_uid_command = [
    'kubectl', '-n', 'kube-system', 'get', "pod/kube-apiserver-${member_name}",
    '--output=jsonpath={.metadata.uid}',
  ].shellquote
  $wait_ready_command = [
    'kubectl', '-n', 'kube-system', 'wait', '--for=condition=Ready',
    "pod/kube-apiserver-${member_name}", '--timeout=180s',
  ].shellquote
  $direct_ready_command = [
    'kubectl', '--kubeconfig=/etc/kubernetes/admin.conf',
    "--server=https://${member_name}:6443", 'get', '--raw=/readyz?verbose',
  ].shellquote

  $etcd_gate_command = @(COMMAND/L)
    set -eu
    tmpdir="$(mktemp -d /tmp/nest-etcd-gate.XXXXXX)"
    trap 'rm -rf "$tmpdir"' EXIT
    kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system exec etcd-${member_name_quoted} -- \
      etcdctl --endpoints=${endpoint_csv_quoted} \
      --cacert=/etc/kubernetes/pki/etcd/ca.crt \
      --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
      --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
      endpoint health --cluster --write-out=table
    kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system exec etcd-${member_name_quoted} -- \
      etcdctl --endpoints=${endpoint_csv_quoted} \
      --cacert=/etc/kubernetes/pki/etcd/ca.crt \
      --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
      --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
      endpoint status --cluster --write-out=json > "$tmpdir/status.json"
    kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system exec etcd-${member_name_quoted} -- \
      etcdctl --endpoints=${endpoint_csv_quoted} \
      --cacert=/etc/kubernetes/pki/etcd/ca.crt \
      --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
      --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
      member list --write-out=json > "$tmpdir/members.json"
    /usr/local/sbin/validate-etcd-cluster "$tmpdir/status.json" "$tmpdir/members.json" 1000 ${member_names_string}
    | COMMAND

  run_command($ready_command, 'localhost', 'Require Kubernetes API readiness')
  run_command($etcd_gate_command, $member, 'Require exact healthy synchronized etcd topology', {
    _run_as => 'root',
  })
  run_command("test -d ${patches_quoted} && test -x /usr/local/sbin/reconcile-kubeadm-cluster-config && test -x /usr/local/sbin/validate-etcd-cluster", $member, 'Require managed kubeadm assets', {
    _run_as => 'root',
  })

  $lock_owner = run_command('cat /proc/sys/kernel/random/uuid', $member, 'Create reconciliation lock owner', {
    _run_as => 'root',
  }).first.value['stdout'].chomp
  $lock_owner_quoted = $lock_owner.shellquote
  $acquire_lock_command = [
    'kubectl', '--kubeconfig=/etc/kubernetes/admin.conf', '-n', 'kube-system',
    'create', 'configmap', $lock_name, "--from-literal=owner=${lock_owner}",
    "--from-literal=member=${member_name}",
  ].shellquote
  $release_lock_command = @(COMMAND/L)
    set -eu
    owner="$(kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system get configmap ${lock_name_quoted} --output=jsonpath='{.data.owner}')"
    [ "$owner" = ${lock_owner_quoted} ]
    kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system delete configmap ${lock_name_quoted} --wait=true
    | COMMAND

  $timestamp = run_command('date -u +%Y%m%dT%H%M%S.%N', $member, 'Create unique reconciliation timestamp', {
    _run_as => 'root',
  }).first.value['stdout'].chomp
  $backup_dir      = "/root/kubernetes-manifest-backups/reconcile-${member_name}-${timestamp}"
  $config_path     = "${backup_dir}/kubeadm-cluster-config.desired.yaml"
  $config_backup   = "${backup_dir}/kubeadm-cluster-config.before.yaml"
  $manifest_backup = "${backup_dir}/kube-apiserver.before.yaml"
  $backup_dir_quoted      = $backup_dir.shellquote
  $config_path_quoted     = $config_path.shellquote
  $config_backup_quoted   = $config_backup.shellquote
  $manifest_backup_quoted = $manifest_backup.shellquote
  $compare_command = [
    '/usr/local/sbin/reconcile-kubeadm-cluster-config', '--compare', $config_backup,
  ].shellquote

  $prepare_config_command = @(COMMAND/L)
    install -d -m 0700 ${backup_dir_quoted} && \
    ${read_config_command} > ${config_backup_quoted} && \
    install -m 0600 ${manifest_quoted} ${manifest_backup_quoted} && \
    ${rewrite_command_string} < ${config_backup_quoted} > ${config_path_quoted}
    | COMMAND
  run_command($prepare_config_command, $member, 'Render desired kubeadm ClusterConfiguration', {
    _run_as => 'root',
  })

  $reconcile_command = "kubeadm upgrade node phase control-plane --config=${config_path_quoted} --patches=${patches_quoted}"
  run_command("kubeadm config validate --config=${config_path_quoted} && ${reconcile_command} --dry-run", $member, 'Validate and dry-run desired control-plane manifest', {
    _run_as => 'root',
  })

  $old_uid = run_command($get_uid_command, 'localhost', "Capture kube-apiserver ${member_name} mirror-Pod UID").first.value['stdout'].chomp
  $old_uid_quoted = $old_uid.shellquote
  $wait_new_uid_script = @(SCRIPT/L)
    while :; do
      current_uid="$(${get_uid_command} 2>/dev/null || true)"
      [ -n "\$current_uid" ] && [ "\$current_uid" != ${old_uid_quoted} ] && break
      sleep 2
    done
    | SCRIPT
  $wait_new_uid_command = ['timeout', '240', 'sh', '-c', $wait_new_uid_script].shellquote

  run_command($acquire_lock_command, $member, 'Acquire cluster-wide control-plane reconciliation lock', {
    _run_as => 'root',
  })
  $freshness = catch_errors() || {
    run_command("${read_config_command} | ${compare_command} && cmp ${manifest_backup_quoted} ${manifest_quoted}", $member, 'Require preflight inputs to remain unchanged after lock acquisition', {
      _run_as => 'root',
    })
    run_command("test \"$(${get_uid_command})\" = ${old_uid_quoted}", 'localhost', 'Require preflight kube-apiserver UID to remain current after lock acquisition')
  }
  if $freshness =~ Error {
    run_command($release_lock_command, $member, 'Release reconciliation lock after stale preflight', {
      _run_as => 'root',
    })
    fail_plan("Control-plane state changed between preflight and lock acquisition; refusing stale rollout: ${freshness.message}; evidence: ${backup_dir}", 'nest/kubernetes-reconcile-stale-preflight')
  }

  $transaction = catch_errors() || {
    run_command("kubeadm init phase upload-config kubeadm --config=${config_path_quoted}", $member, 'Upload kubeadm ClusterConfiguration', {
      _run_as => 'root',
    })
    run_command("${read_config_command} | ${check_command_string}", $member, 'Verify kubeadm ClusterConfiguration readback', {
      _run_as => 'root',
    })
    run_command($reconcile_command, $member, 'Reconcile one control-plane manifest', {
      _run_as => 'root',
    })
    run_command("grep -F -- ${etcd_arg_quoted} ${manifest_quoted}", $member, 'Verify on-disk kube-apiserver endpoints', {
      _run_as => 'root',
    })
    run_command($wait_new_uid_command, 'localhost', "Wait for kube-apiserver ${member_name} mirror-Pod UID to change")
    run_command($wait_ready_command, 'localhost', "Wait for replacement kube-apiserver ${member_name}")
    run_command($direct_ready_command, $member, "Require direct kube-apiserver ${member_name} readiness", {
      _run_as => 'root',
    })
    run_command($ready_command, 'localhost', 'Recheck Kubernetes API readiness')
    run_command($etcd_gate_command, $member, 'Recheck exact healthy synchronized etcd topology', {
      _run_as => 'root',
    })
  }

  if $transaction =~ Error {
    warning("Control-plane reconciliation failed; restoring ${backup_dir}: ${transaction.message}")
    $config_restore = catch_errors() || {
      run_command("kubeadm init phase upload-config kubeadm --config=${config_backup_quoted}", $member, 'Restore kubeadm ConfigMap', {
        _run_as => 'root',
      })
      run_command("${read_config_command} | ${compare_command}", $member, 'Verify restored kubeadm ClusterConfiguration', {
        _run_as => 'root',
      })
    }

    $manifest_restore = catch_errors() || {
      $manifest_state = run_command("if cmp -s ${manifest_backup_quoted} ${manifest_quoted}; then printf same; else printf changed; fi", $member, 'Determine whether rollback requires static-Pod turnover', {
        _run_as => 'root',
      }).first.value['stdout'].chomp

      if $manifest_state == 'changed' {
        $rollback_uid = run_command("${get_uid_command} 2>/dev/null || true", 'localhost', 'Capture pre-rollback kube-apiserver UID').first.value['stdout'].chomp
        $rollback_uid_quoted = $rollback_uid.shellquote
        run_command("install -m 0600 ${manifest_backup_quoted} ${manifest_quoted}", $member, 'Restore local static manifest independently', {
          _run_as => 'root',
        })
        $wait_rollback_uid_script = @(SCRIPT/L)
          while :; do
            current_uid="$(${get_uid_command} 2>/dev/null || true)"
            [ -n "\$current_uid" ] && { [ -z ${rollback_uid_quoted} ] || [ "\$current_uid" != ${rollback_uid_quoted} ]; } && break
            sleep 2
          done
          | SCRIPT
        $wait_rollback_uid_command = ['timeout', '240', 'sh', '-c', $wait_rollback_uid_script].shellquote
        run_command($wait_rollback_uid_command, 'localhost', "Wait for restored kube-apiserver ${member_name} mirror-Pod turnover")
        run_command($wait_ready_command, 'localhost', "Wait for restored kube-apiserver ${member_name}")
      }

      run_command("cmp ${manifest_backup_quoted} ${manifest_quoted}", $member, 'Verify restored static manifest', {
        _run_as => 'root',
      })
      run_command($direct_ready_command, $member, "Require restored kube-apiserver ${member_name} readiness", {
        _run_as => 'root',
      })
      run_command($ready_command, 'localhost', 'Require restored Kubernetes API readiness')
      run_command($etcd_gate_command, $member, 'Require restored exact healthy synchronized etcd topology', {
        _run_as => 'root',
      })
    }
  } else {
    $config_restore   = undef
    $manifest_restore = undef
  }

  $release = catch_errors() || {
    run_command($release_lock_command, $member, 'Release cluster-wide control-plane reconciliation lock', {
      _run_as => 'root',
    })
  }

  if $release =~ Error {
    fail_plan("Control-plane reconciliation lock release failed for owner ${lock_owner}; backups: ${backup_dir}; error: ${release.message}", 'nest/kubernetes-reconcile-lock-release-failed')
  }

  if $transaction =~ Error {
    if $config_restore =~ Error or $manifest_restore =~ Error {
      fail_plan("Control-plane reconciliation failed (${transaction.message}); independent rollback errors: config=${config_restore}, manifest=${manifest_restore}; backups: ${backup_dir}", 'nest/kubernetes-reconcile-rollback-failed')
    }
    fail_plan("Control-plane reconciliation failed and was rolled back from ${backup_dir}: ${transaction.message}", 'nest/kubernetes-reconcile-rolled-back')
  }

  notice("Control-plane reconciliation completed; immutable rollback evidence: ${backup_dir}")
}
