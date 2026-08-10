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
  if $restore {
    $restore_targets = get_targets($targets)
    if $restore_targets.length != 1 {
      fail('registry restore requires exactly one shared backup target')
    }

    $restore_target = $restore_targets[0]
    $bucket_config = nest::kubernetes::bucket_config($service, $namespace)
    $lock_file     = '/run/lock/nest-registry-backup-restore.lock'
    $backup_root   = "/nest/backup/${service}"
    $helper        = '/tmp/nest-registry-restore-generation'

    upload_file('nest/registry-restore-generation', $helper, $restore_target, {
      '_run_as' => 'root',
    })

    $restore_cmd = [
      'flock',
      '--exclusive',
      $lock_file,
      $helper,
      $backup_root,
      "s3://${bucket_config['BUCKET_NAME']}/",
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
    ].flatten.shellquote

    run_command("chmod 0700 ${helper.shellquote} && ${restore_cmd}", $restore_target, 'Restore only the atomically published registry backup generation', {
      '_run_as' => 'root',
    })

    run_command("rm -f ${helper.shellquote}", $restore_target, 'Remove registry restore helper', {
      '_run_as' => 'root',
    })
  }
}
