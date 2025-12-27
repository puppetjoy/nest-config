# Backup a registry instance
#
# @param targets Backup host
# @param namespace Kubernetes namespace
# @param service Kubernetes service
# @param service_name Unused
plan nest::eyrie::registry::backup (
  TargetSpec       $targets      = 'eyrie-workstations',
  String           $namespace    = 'default',
  String           $service      = 'registry',
  Optional[String] $service_name = undef, # unused
) {
  $backup_target = get_targets($targets)[0]
  $bucket_config = nest::kubernetes::bucket_config($service, $namespace)

  $backup_cmd = [
    's3cmd',
    'sync',
    '--delete-removed',
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
}
