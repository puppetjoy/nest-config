class nest::base::containers {
  unless $facts['is_container'] or $facts['mountpoints']['/var/lib/containers'] or !$nest::zfs {
    zfs { 'containers':
      name       => "${facts['rpool'].regsubst('/crypt$', '')}/containers",
      mountpoint => '/var/lib/containers',
    }
  }

  # Preselect optional dependencies
  nest::lib::package { [
    'app-containers/crun',
    'app-containers/netavark',
  ]:,
    ensure => installed,
  }
  ->
  nest::lib::package { 'app-containers/podman':
    ensure => installed,
  }
  ->
  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/containers/containers.conf':
      source => 'puppet:///modules/nest/containers/containers.conf'
    ;

    '/etc/containers/policy.json':
      source => 'puppet:///modules/nest/containers/policy.json',
    ;

    '/etc/containers/registries.conf':
      source => 'puppet:///modules/nest/containers/registries.conf',
    ;

    '/etc/systemd/system/podman.service.d':
      ensure => directory,
    ;

    '/etc/systemd/system/podman.service.d/10-delegate.conf':
      content => "[Service]\nDelegate=yes\n",
      notify  => Nest::Lib::Systemd_reload['containers'],
    ;
  }
  ->
  nest::lib::systemd_reload { 'containers': }
  ->
  service { [
    'podman.socket',
    'netavark-firewalld-reload',
  ]:
    enable => true,
  }

  $rootless_users = [$nest::user]
  $subuidgid_content = $rootless_users.map |$index, $user| {
    $subuidgid = 65536 * $index + 100000
    "${user}:${subuidgid}:65536\n"
  }.join

  file { [
    '/etc/subuid',
    '/etc/subgid',
  ]:
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $subuidgid_content,
    require => Class['nest::base::users'], # overwrite generated entries
  }

  #
  # XXX Cleanup
  #
  service { 'podman-firewalld-reload':
    ensure => stopped,
    enable => false,
  }
  ->
  file { '/etc/systemd/system/podman-firewalld-reload.service':
    ensure => absent,
  }
}
