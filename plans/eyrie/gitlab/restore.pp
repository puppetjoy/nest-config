# Restore a GitLab instance
#
# @see https://docs.gitlab.com/charts/backup-restore/restore/
#
# @param targets Restore host
# @param namespace Kubernetes namespace
# @param service Kubernetes service
# @param service_name Unused
# @param restore Safety gate
plan nest::eyrie::gitlab::restore (
  TargetSpec       $targets      = 'eyrie-workstations',
  String           $namespace    = 'test',
  String           $service      = 'gitlab',
  Optional[String] $service_name = undef, # unused
  Boolean          $restore      = false,
) {
  if $restore {
    $restore_target = get_targets($targets)[0]
    $bucket_config = nest::kubernetes::bucket_config("${service}-backups", $namespace)

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

    $put_cmd = [
      's3cmd',
      'put',
      '--follow-symlinks',
      '--no-ssl',
      "--access_key=${bucket_config['AWS_ACCESS_KEY_ID']}",
      "--secret_key=${bucket_config['AWS_SECRET_ACCESS_KEY']}",
      "--host=${bucket_config['BUCKET_HOST']}",
      "--host-bucket=%(bucket)s.${bucket_config['BUCKET_HOST']}",
      "/nest/backup/${service}/latest_gitlab_backup.tar",
      "s3://${bucket_config['BUCKET_NAME']}/",
    ].flatten.shellquote

    run_command($put_cmd, $restore_target, 's3cmd put', {
      '_run_as' => 'root',
    })

    $backup_utility_cmd = [
      'kubectl', 'exec', '-n', $namespace,
      "deploy/${service}-toolbox",
      '--',
      'backup-utility',
      '--restore',
      '--skip-restore-prompt',
      '-t', 'latest',
    ].flatten.shellquote

    run_command($backup_utility_cmd, 'localhost', "${service} backup-utility restore")

    $kubectl_scale_up_cmd = [
      'kubectl', 'scale', 'deployments', '-n', $namespace,
      "${service}-prometheus-server",
      "${service}-sidekiq-all-in-1-v2",
      "${service}-webservice-default",
      '--replicas=1',
    ].flatten.shellquote

    run_command($kubectl_scale_up_cmd, 'localhost', "Start ${service}")
  }
}
