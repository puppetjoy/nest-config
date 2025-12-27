# Restore a registry instance
#
# @param targets Restore host
# @param namespace Kubernetes namespace
# @param service Kubernetes service
# @param service_name Unused
# @param restore Safety gate
plan nest::eyrie::registry::restore (
  TargetSpec       $targets      = 'eyrie-workstations',
  String           $namespace    = 'test',
  String           $service      = 'registry',
  Optional[String] $service_name = undef, # unused
  Boolean          $restore      = false,
) {
  $restore_target = get_targets($targets)[0]
  $bucket_config = nest::kubernetes::bucket_config($service, $namespace)

  $restore_cmd = [
    's3cmd',
    'sync',
    '--delete-removed',
    '--skip-existing',
    '--no-preserve',
    '--no-ssl',
    '--multipart-chunk-size-mb=64',
    "--access_key=${bucket_config['AWS_ACCESS_KEY_ID']}",
    "--secret_key=${bucket_config['AWS_SECRET_ACCESS_KEY']}",
    "--host=${bucket_config['BUCKET_HOST']}",
    "--host-bucket=%(bucket)s.${bucket_config['BUCKET_HOST']}",
    "/nest/backup/${service}/",
    "s3://${bucket_config['BUCKET_NAME']}/",
  ].flatten.shellquote

  run_command($restore_cmd, $restore_target, 's3cmd', {
    '_run_as' => 'root',
  })
}
