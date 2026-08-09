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
  $backup_targets = get_targets($targets)
  if $backup_targets.length != 1 {
    fail('registry backup requires exactly one shared backup target')
  }

  $backup_target = $backup_targets[0]
  $bucket_config = nest::kubernetes::bucket_config($service, $namespace)
  $lock_file     = '/run/lock/nest-registry-backup-restore.lock'
  $backup_root   = "/nest/backup/${service}"
  $helper        = '/tmp/nest-registry-backup-generation'

  upload_file('nest/registry-backup-generation', $helper, $backup_target, {
    '_run_as' => 'root',
  })

  $backup_cmd = [
    'flock',
    '--exclusive',
    '--nonblock',
    $lock_file,
    $helper,
    $backup_root,
    '--',
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
  ].flatten.shellquote

  run_command("chmod 0700 ${helper.shellquote} && ${backup_cmd}", $backup_target, 'Publish immutable completed registry backup generation', {
    '_run_as' => 'root',
  })

  run_command("rm -f ${helper.shellquote}", $backup_target, 'Remove registry backup helper', {
    '_run_as' => 'root',
  })
}
