# Reconcile GitLab Gitaly's retained claim with the source-managed claim template.
#
# This plan is intentionally review-gated. With reconcile=false it performs all
# identity, backup/restore, storage, and rendered-chart preflight checks without
# changing Kubernetes resources. A mutating run must bind the expected PVC/PV
# UIDs observed by the reviewed preflight.
#
# The persistent volume has a Delete reclaim policy. The plan therefore refuses
# to delete the PVC or PV, requires StatefulSet claim retention to be Retain,
# and deletes only the StatefulSet with orphan propagation.
plan nest::eyrie::gitlab::reconcile_gitaly_storage (
  Enum['test', 'default'] $namespace,
  String[1]               $expected_pvc_uid,
  String[1]               $expected_pv_uid,
  String[1]               $backup_job,
  String[1]               $restore_job,
  String                  $service                    = 'gitlab',
  String                  $chart_version              = '10.0.1',
  String                  $current_template_size      = '50Gi',
  String                  $current_pvc_size           = '50Gi',
  String                  $desired_size               = '100Gi',
  Integer[1]              $evidence_max_age_hours     = 24,
  String                  $https_smoke_repository     = '',
  String                  $ssh_smoke_repository       = '',
  Boolean                 $reconcile                  = false,
) {
  if $service !~ Pattern[/\A[a-z0-9]([-a-z0-9]*[a-z0-9])?\z/] {
    fail('service must be a Kubernetes DNS label')
  }
  if $chart_version != '10.0.1' {
    fail('Gitaly storage reconciliation is pinned to GitLab chart 10.0.1')
  }
  if $desired_size != '100Gi' {
    fail('Gitaly storage reconciliation is pinned to the reviewed 100Gi target')
  }
  if $reconcile and ($https_smoke_repository == '' or $ssh_smoke_repository == '') {
    fail('Mutating reconciliation requires HTTPS and SSH smoke repository URLs')
  }

  $statefulset = "${service}-gitaly"
  $claim       = "repo-data-${statefulset}-0"
  $render_path = "/tmp/${service}-${namespace}-gitaly-storage-reconcile.yaml"

  $identity_script = @("SCRIPT"/L$)
    set -eu
    namespace=${namespace.shellquote}
    statefulset=${statefulset.shellquote}
    claim=${claim.shellquote}
    expected_pvc_uid=${expected_pvc_uid.shellquote}
    expected_pv_uid=${expected_pv_uid.shellquote}
    expected_template_size=${current_template_size.shellquote}
    expected_pvc_size=${current_pvc_size.shellquote}

    replicas=\$(kubectl get statefulset "\${statefulset}" -n "\${namespace}" -o jsonpath='{.spec.replicas}')
    retention=\$(kubectl get statefulset "\${statefulset}" -n "\${namespace}" -o jsonpath='{.spec.persistentVolumeClaimRetentionPolicy.whenDeleted}')
    template_size=\$(kubectl get statefulset "\${statefulset}" -n "\${namespace}" -o jsonpath='{.spec.volumeClaimTemplates[0].spec.resources.requests.storage}')
    pvc_uid=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.metadata.uid}')
    pv_name=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.spec.volumeName}')
    pvc_size=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.status.capacity.storage}')
    pvc_phase=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.status.phase}')
    pv_uid=\$(kubectl get pv "\${pv_name}" -o jsonpath='{.metadata.uid}')
    reclaim=\$(kubectl get pv "\${pv_name}" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}')

    [ "\${replicas}" = 1 ]
    [ "\${retention}" = Retain ]
    [ "\${template_size}" = "\${expected_template_size}" ]
    [ "\${pvc_uid}" = "\${expected_pvc_uid}" ]
    [ "\${pv_uid}" = "\${expected_pv_uid}" ]
    [ "\${pvc_phase}" = Bound ]
    [ "\${pvc_size}" = "\${expected_pvc_size}" ]
    [ "\${reclaim}" = Delete ]

    printf 'namespace=%s statefulset=%s claim=%s pvc_uid=%s pv=%s pv_uid=%s template=%s pvc_capacity=%s retention=%s reclaim=%s\n' \
      "\${namespace}" "\${statefulset}" "\${claim}" "\${pvc_uid}" "\${pv_name}" "\${pv_uid}" "\${template_size}" "\${pvc_size}" "\${retention}" "\${reclaim}"
    | SCRIPT

  run_command(['sh', '-c', $identity_script].shellquote, 'localhost', 'Verify and record Gitaly PVC/PV identity')

  $evidence_script = @("SCRIPT"/L$)
    set -eu
    max_age_seconds=\$((${evidence_max_age_hours} * 3600))
    now=\$(date +%s)
    check_job() {
      namespace=\$1
      job=\$2
      complete=\$(kubectl get job "\${job}" -n "\${namespace}" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
      completed_at=\$(kubectl get job "\${job}" -n "\${namespace}" -o jsonpath='{.status.completionTime}')
      [ "\${complete}" = True ]
      [ -n "\${completed_at}" ]
      completed_epoch=\$(date -d "\${completed_at}" +%s)
      age=\$((now - completed_epoch))
      [ "\${age}" -ge 0 ]
      [ "\${age}" -le "\${max_age_seconds}" ]
      printf '%s/%s complete age_seconds=%s\n' "\${namespace}" "\${job}" "\${age}"
    }
    check_job default ${backup_job.shellquote}
    check_job test ${restore_job.shellquote}
    | SCRIPT

  run_command(['sh', '-c', $evidence_script].shellquote, 'localhost', 'Verify fresh GitLab backup and test-restore evidence')

  if $namespace == 'default' {
    $test_gate_script = @("SCRIPT"/L$)
      set -eu
      test_template=\$(kubectl get statefulset ${statefulset.shellquote} -n test -o jsonpath='{.spec.volumeClaimTemplates[0].spec.resources.requests.storage}')
      test_ready=\$(kubectl get statefulset ${statefulset.shellquote} -n test -o jsonpath='{.status.readyReplicas}')
      test_capacity=\$(kubectl get pvc ${claim.shellquote} -n test -o jsonpath='{.status.capacity.storage}')
      [ "\${test_template}" = ${desired_size.shellquote} ]
      [ "\${test_capacity}" = ${desired_size.shellquote} ]
      [ "\${test_ready}" = 1 ]
      | SCRIPT

    run_command(['sh', '-c', $test_gate_script].shellquote, 'localhost', 'Require completed test Gitaly storage reconciliation before production')
    run_command([
      'kubectl', 'exec', '-n', 'test', "deployment/${service}-toolbox",
      '--', 'gitlab-rake', 'gitlab:gitaly:check',
    ].shellquote, 'localhost', 'Require healthy test Gitaly before production')
  }

  run_plan('nest::eyrie::gitlab::deploy', {
    namespace     => $namespace,
    service       => $service,
    chart_version => $chart_version,
    deploy        => true,
    resources     => false,
    gitlab        => true,
    hooks         => false,
    render_to     => $render_path,
  })

  $render_check_script = @("SCRIPT"/L)
    require 'yaml'
    documents = YAML.load_stream(File.read(ARGV.fetch(0))).compact
    statefulset = documents.find do |document|
      document['kind'] == 'StatefulSet' && document.dig('metadata', 'name') == ARGV.fetch(1)
    end
    abort('rendered Gitaly StatefulSet not found') unless statefulset
    size = statefulset.dig('spec', 'volumeClaimTemplates', 0, 'spec', 'resources', 'requests', 'storage')
    abort("rendered claim template is #{size.inspect}, expected #{ARGV.fetch(2)}") unless size == ARGV.fetch(2)
    puts "rendered #{ARGV.fetch(1)} claim template=#{size}"
    | SCRIPT

  run_command([
    'ruby', '-e', $render_check_script,
    $render_path, $statefulset, $desired_size,
  ].shellquote, 'localhost', 'Verify chart 10.0.1 renders the desired Gitaly claim template')

  if !$reconcile {
    out::message("Gitaly storage preflight passed for ${namespace}; reconcile=false, so no Kubernetes resources were changed")
    return({
      namespace        => $namespace,
      statefulset      => $statefulset,
      claim            => $claim,
      expected_pvc_uid => $expected_pvc_uid,
      expected_pv_uid  => $expected_pv_uid,
      chart_version    => $chart_version,
      desired_size     => $desired_size,
      reconciled       => false,
    })
  }

  run_command([
    'kubectl', 'scale', 'statefulset', $statefulset,
    '-n', $namespace, '--replicas=0',
  ].shellquote, 'localhost', 'Scale Gitaly to zero')

  $wait_stopped_script = @("SCRIPT"/L$)
    set -eu
    for unused in \$(seq 1 120); do
      current=\$(kubectl get pods -n ${namespace.shellquote} -l app=gitaly,release=${service.shellquote} --no-headers 2>/dev/null | wc -l)
      [ "\${current}" -eq 0 ] && exit 0
      sleep 5
    done
    echo 'Gitaly pod did not stop within 10 minutes' >&2
    exit 1
    | SCRIPT

  run_command(['sh', '-c', $wait_stopped_script].shellquote, 'localhost', 'Wait for Gitaly to stop')

  if $current_pvc_size != $desired_size {
    $resize_patch = "{\"spec\":{\"resources\":{\"requests\":{\"storage\":\"${desired_size}\"}}}}"
    run_command([
      'kubectl', 'patch', 'pvc', $claim, '-n', $namespace,
      '--type=merge', '-p', $resize_patch,
    ].shellquote, 'localhost', 'Expand the existing Gitaly PVC')
  }

  $wait_resize_script = @("SCRIPT"/L$)
    set -eu
    for unused in \$(seq 1 120); do
      requested=\$(kubectl get pvc ${claim.shellquote} -n ${namespace.shellquote} -o jsonpath='{.spec.resources.requests.storage}')
      capacity=\$(kubectl get pvc ${claim.shellquote} -n ${namespace.shellquote} -o jsonpath='{.status.capacity.storage}')
      phase=\$(kubectl get pvc ${claim.shellquote} -n ${namespace.shellquote} -o jsonpath='{.status.phase}')
      if [ "\${requested}" = ${desired_size.shellquote} ] && [ "\${capacity}" = ${desired_size.shellquote} ] && [ "\${phase}" = Bound ]; then
        exit 0
      fi
      sleep 5
    done
    kubectl get pvc ${claim.shellquote} -n ${namespace.shellquote} -o wide >&2
    echo 'Gitaly PVC did not reach the desired bound capacity within 10 minutes' >&2
    exit 1
    | SCRIPT

  run_command(['sh', '-c', $wait_resize_script].shellquote, 'localhost', 'Wait for CSI capacity expansion')

  run_command([
    'kubectl', 'delete', 'statefulset', $statefulset,
    '-n', $namespace, '--cascade=orphan', '--wait=true',
  ].shellquote, 'localhost', 'Delete only the retained-claim Gitaly StatefulSet')

  run_plan('nest::eyrie::gitlab::deploy', {
    namespace     => $namespace,
    service       => $service,
    chart_version => $chart_version,
    deploy        => true,
    hooks         => false,
    init           => false,
  })

  run_command([
    'kubectl', 'rollout', 'status', 'statefulset', $statefulset,
    '-n', $namespace, '--timeout=15m',
  ].shellquote, 'localhost', 'Wait for recreated Gitaly StatefulSet')

  $postcheck_script = @("SCRIPT"/L$)
    set -eu
    namespace=${namespace.shellquote}
    statefulset=${statefulset.shellquote}
    claim=${claim.shellquote}
    expected_pvc_uid=${expected_pvc_uid.shellquote}
    expected_pv_uid=${expected_pv_uid.shellquote}
    desired_size=${desired_size.shellquote}

    template_size=\$(kubectl get statefulset "\${statefulset}" -n "\${namespace}" -o jsonpath='{.spec.volumeClaimTemplates[0].spec.resources.requests.storage}')
    retention=\$(kubectl get statefulset "\${statefulset}" -n "\${namespace}" -o jsonpath='{.spec.persistentVolumeClaimRetentionPolicy.whenDeleted}')
    pvc_uid=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.metadata.uid}')
    pv_name=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.spec.volumeName}')
    pvc_capacity=\$(kubectl get pvc "\${claim}" -n "\${namespace}" -o jsonpath='{.status.capacity.storage}')
    pv_uid=\$(kubectl get pv "\${pv_name}" -o jsonpath='{.metadata.uid}')

    [ "\${template_size}" = "\${desired_size}" ]
    [ "\${retention}" = Retain ]
    [ "\${pvc_uid}" = "\${expected_pvc_uid}" ]
    [ "\${pv_uid}" = "\${expected_pv_uid}" ]
    [ "\${pvc_capacity}" = "\${desired_size}" ]

    mounted_bytes=\$(kubectl exec -n "\${namespace}" "statefulset/\${statefulset}" -- df -B1 --output=size /home/git/repositories | tail -1 | tr -d ' ')
    [ "\${mounted_bytes}" -ge 107374182400 ]

    printf 'reconciled namespace=%s claim=%s pvc_uid=%s pv=%s pv_uid=%s template=%s pvc_capacity=%s mounted_bytes=%s\n' \
      "\${namespace}" "\${claim}" "\${pvc_uid}" "\${pv_name}" "\${pv_uid}" "\${template_size}" "\${pvc_capacity}" "\${mounted_bytes}"
    | SCRIPT

  run_command(['sh', '-c', $postcheck_script].shellquote, 'localhost', 'Verify retained claim identity, template parity, and mounted filesystem')

  run_command([
    'kubectl', 'exec', '-n', $namespace, "deployment/${service}-toolbox",
    '--', 'gitlab-rake', 'gitlab:gitaly:check',
  ].shellquote, 'localhost', 'Verify GitLab can access Gitaly repositories')

  $git_smoke_script = @("SCRIPT"/L$)
    set -eu
    url=\$1
    protocol=\$2
    workdir=\$(mktemp -d)
    branch="talon-gitaly-storage-smoke-\${protocol}-\$(date +%s)"
    pushed=false
    cleanup() {
      if [ "\${pushed}" = true ]; then
        git -C "\${workdir}/repo" push --quiet origin --delete "\${branch}" || true
      fi
      rm -rf "\${workdir}"
    }
    trap cleanup EXIT INT TERM

    git clone --quiet "\${url}" "\${workdir}/repo"
    git -C "\${workdir}/repo" switch --quiet -c "\${branch}"
    git -C "\${workdir}/repo" -c user.name=Talon -c user.email=talon@joyfullee.me \
      commit --quiet --allow-empty -m 'test: verify Gitaly storage reconciliation'
    git -C "\${workdir}/repo" push --quiet origin "\${branch}"
    pushed=true
    git -C "\${workdir}/repo" fetch --quiet origin "\${branch}"
    git -C "\${workdir}/repo" push --quiet origin --delete "\${branch}"
    pushed=false
    printf '%s clone/fetch/push smoke passed\n' "\${protocol}"
    | SCRIPT

  run_command([
    'sh', '-c', $git_smoke_script, 'git-smoke',
    $https_smoke_repository, 'https',
  ].shellquote, 'localhost', 'Verify Git clone, fetch, and push over HTTPS')
  run_command([
    'sh', '-c', $git_smoke_script, 'git-smoke',
    $ssh_smoke_repository, 'ssh',
  ].shellquote, 'localhost', 'Verify Git clone, fetch, and push over SSH')

  return({
    namespace        => $namespace,
    statefulset      => $statefulset,
    claim            => $claim,
    expected_pvc_uid => $expected_pvc_uid,
    expected_pv_uid  => $expected_pv_uid,
    chart_version    => $chart_version,
    desired_size     => $desired_size,
    reconciled       => true,
  })
}
