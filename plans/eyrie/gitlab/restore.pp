# Restore a GitLab instance
#
# @see https://docs.gitlab.com/charts/backup-restore/restore/
#
# @param targets Restore host
# @param namespace Kubernetes namespace
# @param service Kubernetes service
# @param service_name Unused
# @param home_page_url Post-restore GitLab home page URL
# @param restore Safety gate
plan nest::eyrie::gitlab::restore (
  TargetSpec       $targets           = 'eyrie-workstations',
  String           $namespace         = 'test',
  String           $service           = 'gitlab',
  Optional[String] $service_name      = undef, # unused
  String           $home_page_url     = "https://${service}-${namespace}.eyrie/explore",
  String           $backups_namespace = 'default',
  Optional[String] $backup_timestamp  = undef,
  Boolean          $restore           = false,
) {
  if $restore {
    $kubectl_scale_up_cmd = [
      'kubectl', 'scale', 'deployments', '-n', $namespace,
      "${service}-prometheus-server",
      "${service}-sidekiq-all-in-1-v2",
      "${service}-webservice-default",
      '--replicas=1',
    ].flatten.shellquote

    $kubectl_scale_down_cmd = [
      'kubectl', 'scale', 'deployments', '-n', $namespace,
      "${service}-prometheus-server",
      "${service}-sidekiq-all-in-1-v2",
      "${service}-toolbox",
      "${service}-webservice-default",
      '--replicas=0',
    ].flatten.shellquote

    run_command($kubectl_scale_down_cmd, 'localhost', "Stop ${service}")

    $kubectl_delete_secret_cmd = [
      'kubectl', 'delete', 'secret', '-n', $namespace,
      "${service}-rails-secret",
    ].flatten.shellquote

    run_command($kubectl_delete_secret_cmd, 'localhost', "Delete ${service}-rails secret")

    $kubectl_create_secret_cmd = [
      'kubectl', 'create', 'secret', 'generic', '-n', $namespace,
      "${service}-rails-secret",
      "--from-file=secrets.yml=/nest/backup/${service}/gitlab-secrets.yaml",
    ].flatten.shellquote

    run_command($kubectl_create_secret_cmd, 'localhost', "Create ${service}-rails secret")

    $kubectl_scale_up_toolbox_cmd = [
      'kubectl', 'scale', 'deployment', '-n', $namespace,
      "${service}-toolbox",
      '--replicas=1',
    ].flatten.shellquote

    run_command($kubectl_scale_up_toolbox_cmd, 'localhost', "Start ${service}-toolbox")

    $kubectl_wait_toolbox_cmd = [
      'kubectl', 'rollout', 'status', 'deployment', '-n', $namespace,
      "${service}-toolbox",
      '--timeout=5m',
    ].flatten.shellquote


    run_command($kubectl_wait_toolbox_cmd, 'localhost', "Wait for ${service}-toolbox")

    $kubectl_wait_toolbox_exec_cmd = [
      'sh', '-c',
      "for i in $(seq 1 60); do kubectl exec -n ${namespace} deploy/${service}-toolbox -- sh -lc true && exit 0; sleep 5; done; exit 1",
    ].flatten.shellquote

    run_command($kubectl_wait_toolbox_exec_cmd, 'localhost', "Wait for ${service}-toolbox exec")

    $ensure_object_buckets_script = [
      'set -eu',
      'for var in TMP_BUCKET_NAME ARTIFACTS_BUCKET_NAME LFS_BUCKET_NAME PACKAGES_BUCKET_NAME REGISTRY_BUCKET_NAME UPLOADS_BUCKET_NAME; do',
      'eval "bucket=\${$var:-}"',
      '[ -n "$bucket" ] || continue',
      'if ! s3cmd ls "s3://${bucket}/" >/dev/null 2>&1; then',
      's3cmd mb "s3://${bucket}"',
      'fi',
      'done',
    ].join('; ')

    $kubectl_ensure_object_buckets_cmd = [
      'kubectl', 'exec', '-n', $namespace,
      "deploy/${service}-toolbox",
      '--',
      'sh', '-lc', $ensure_object_buckets_script,
    ].flatten.shellquote

    run_command($kubectl_ensure_object_buckets_cmd, 'localhost', "Ensure ${service} object buckets")

    $kubectl_clean_toolbox_backups_cmd = [
      'kubectl', 'exec', '-n', $namespace,
      "deploy/${service}-toolbox",
      '--',
      'sh', '-lc',
      'rm -rf /srv/gitlab/tmp/backups/*',
    ].flatten.shellquote

    run_command($kubectl_clean_toolbox_backups_cmd, 'localhost', "Clean ${service}-toolbox restore workspace")

    $kubectl_clean_repositories_cmd = [
      'kubectl', 'exec', '-n', $namespace,
      "statefulset/${service}-gitaly",
      '--',
      'sh', '-lc',
      'find /home/git/repositories -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +',
    ].flatten.shellquote

    run_command($kubectl_clean_repositories_cmd, 'localhost', "Clean ${service} repositories before restore")

    $backup_bucket_config = nest::kubernetes::bucket_config("${service}-backups", $backups_namespace)
    if !$backup_bucket_config {
      fail("Could not find ${service}-backups bucket config in namespace ${backups_namespace}")
    }

    if $backup_timestamp {
      $restore_timestamp = $backup_timestamp
    } else {
      $latest_backup_cmd = [
        'kubectl', 'exec', '-n', $namespace,
        "deploy/${service}-toolbox",
        '--',
        'sh', '-lc',
        "s3cmd --no-ssl --access_key=${backup_bucket_config['AWS_ACCESS_KEY_ID']} --secret_key=${backup_bucket_config['AWS_SECRET_ACCESS_KEY']} --host=${backup_bucket_config['BUCKET_HOST']} --host-bucket='%(bucket)s.${backup_bucket_config['BUCKET_HOST']}' ls s3://${backup_bucket_config['BUCKET_NAME']}/ | python3 -c 'import sys; backups = [line.split()[-1].rsplit(\"/\", 1)[-1].removesuffix(\"_gitlab_backup.tar\") for line in sys.stdin if line.rstrip().endswith(\"_gitlab_backup.tar\")]; print(backups[-1] if backups else \"\", end=\"\"); sys.exit(0 if backups else 1)'",
      ].flatten.shellquote

      $latest_backup_result = run_command($latest_backup_cmd, 'localhost', "Find latest ${service} backup", _catch_errors => true)
      if !$latest_backup_result.ok {
        run_command($kubectl_scale_up_cmd, 'localhost', "Start ${service}")
        fail("Could not find latest ${service} backup; deployments were scaled back up")
      }

      $restore_timestamp = $latest_backup_result.first.value['stdout'].chomp
    }

    $backup_utility_cmd = [
      'kubectl', 'exec', '-n', $namespace,
      "deploy/${service}-toolbox",
      '--',
      'backup-utility',
      '--restore',
      '--skip-restore-prompt',
      '-t', $restore_timestamp,
    ].flatten.shellquote

    $restore_result = run_command($backup_utility_cmd, 'localhost', "${service} backup-utility restore", _catch_errors => true)

    run_command($kubectl_scale_up_cmd, 'localhost', "Start ${service}")
    if !$restore_result.ok {
      fail("${service} backup-utility restore failed; deployments were scaled back up")
    }

    $home_page_url_cmd = [
      'kubectl', 'exec', '-n', $namespace,
      "deploy/${service}-toolbox",
      '--',
      'gitlab-rails', 'runner',
      "ApplicationSetting.current.update!(home_page_url: '${home_page_url}')",
    ].flatten.shellquote

    $home_page_result = run_command($home_page_url_cmd, 'localhost', "Set ${service} home_page_url", _catch_errors => true)

    if !$home_page_result.ok {
      fail("${service} home_page_url update failed; deployments were scaled back up")
    }
  }
}
