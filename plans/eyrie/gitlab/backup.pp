# Backup a GitLab instance
#
# @see https://docs.gitlab.com/charts/backup-restore/backup/
#
# @param targets Backup host
# @param namespace Kubernetes namespace
# @param service Kubernetes service
# @param service_name Unused
plan nest::eyrie::gitlab::backup (
  TargetSpec       $targets      = 'eyrie-workstations',
  String           $namespace    = 'default',
  String           $service      = 'gitlab',
  Optional[String] $service_name = undef, # unused
) {
  $backup_target = get_targets($targets)[0]
  $bucket_config = nest::kubernetes::bucket_config("${service}-backups", $namespace)

  $kubectl_get_secret_cmd = [
    'kubectl', 'get', 'secret', '-n', $namespace,
    "${service}-rails-secret",
    '-o', 'jsonpath={.data[\'secrets\.yml\']}',
  ].flatten.shellquote

  $secrets = run_command($kubectl_get_secret_cmd, 'localhost', "Get ${service}-rails secrets").first.value['stdout']

  file::write("/nest/backup/${service}/gitlab-secrets.yaml", base64('decode', $secrets))

  $remove_cmd = [
    's3cmd',
    'rm',
    '--recursive',
    '--force',
    '--no-ssl',
    "--access_key=${bucket_config['AWS_ACCESS_KEY_ID']}",
    "--secret_key=${bucket_config['AWS_SECRET_ACCESS_KEY']}",
    "--host=${bucket_config['BUCKET_HOST']}",
    "--host-bucket=%(bucket)s.${bucket_config['BUCKET_HOST']}",
    "s3://${bucket_config['BUCKET_NAME']}/",
  ].flatten.shellquote

  run_command($remove_cmd, $backup_target, 's3cmd rm', {
    '_run_as' => 'root',
  })

  $backup_utility_cmd = [
    'kubectl', 'exec', '-n', $namespace,
    "deploy/${service}-toolbox",
    '--',
    'backup-utility',
    # Too large
    '--skip', 'artifacts',
    '--skip', 'registry',
    # Unused
    '--skip', 'external_diffs',
    '--skip', 'terraform_state',
    '--skip', 'pages',
    '--skip', 'ci_secure_files',
  ].flatten.shellquote

  run_command($backup_utility_cmd, 'localhost', "${service} backup-utility")

  $backup_cmd = [
    's3cmd',
    'sync',
    '--delete-removed',
    '--exclude=gitlab-secrets.yaml',
    '--force',
    '--skip-existing',
    '--no-preserve',
    '--no-ssl',
    '--multipart-chunk-size-mb=64',
    "--access_key=${bucket_config['AWS_ACCESS_KEY_ID']}",
    "--secret_key=${bucket_config['AWS_SECRET_ACCESS_KEY']}",
    "--host=${bucket_config['BUCKET_HOST']}",
    "--host-bucket=%(bucket)s.${bucket_config['BUCKET_HOST']}",
    "s3://${bucket_config['BUCKET_NAME']}/",
    "/nest/backup/${service}/",
  ].flatten.shellquote

  run_command($backup_cmd, $backup_target, 's3cmd sync', {
    '_run_as' => 'root',
  })

  $symlink_cmd = "cd /nest/backup/${service} && rm -f latest_gitlab_backup.tar && ln -s *_gitlab_backup.tar latest_gitlab_backup.tar"

  run_command($symlink_cmd, $backup_target, 'Make deterministic backup ID', {
    '_run_as' => 'root',
  })
}
