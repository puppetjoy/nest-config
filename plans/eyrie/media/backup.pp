# Snapshot the five application configurations, including SQLite WAL files.
plan nest::eyrie::media::backup (
  String $namespace    = 'media',
  String $service      = 'media',
  String $service_name = $service,
) {
  unless $namespace == 'media' and $service == 'media' and $service_name == 'media' {
    fail('The media backup is scoped to Falcon production media')
  }
  $apps = ['nzbget', 'ombi', 'radarr', 'sonarr', 'plex']
  $volumes = $apps.reduce({}) |$result, $app| {
    $claim = parsejson(run_command([
      'kubectl', 'get', 'pvc', "${app}-config", '-n', $namespace, '-o', 'json',
    ].shellquote, 'localhost', 'Resolve retained config claim').first.value['stdout'])
    unless $claim['status']['phase'] == 'Bound' and $claim['spec']['storageClassName'] == 'media-crypt' {
      fail("Media config claim ${app} is not bound to retained media storage")
    }
    $volume = parsejson(run_command([
      'kubectl', 'get', 'pv', $claim['spec']['volumeName'], '-o', 'json',
    ].shellquote, 'localhost', 'Verify retained volume identity').first.value['stdout'])
    unless $volume['spec']['csi']['driver'] == 'zfs.csi.openebs.io' and
      $volume['spec']['persistentVolumeReclaimPolicy'] == 'Retain' and
      $volume['spec']['claimRef']['namespace'] == $namespace and
      $volume['spec']['claimRef']['name'] == "${app}-config" {
      fail("Unexpected media volume identity for ${app}")
    }
    $result + { $app => $volume['spec']['csi']['volumeHandle'] }
  }
  return run_task('nest::media_backup', 'falcon', {
    'volumes' => $volumes,
    '_run_as' => 'root',
  })
}
