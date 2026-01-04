define nest::lib::container (
  String               $image,
  Array[String]        $cap_add    = [],
  Array[String]        $command    = [],
  Optional[String]     $dns        = undef,
  Array[String]        $devices    = [],
  Nest::ServiceEnsure  $ensure     = running,
  Optional[String]     $entrypoint = undef,
  Array[String]        $env        = [],
  Optional[String]     $network    = undef,
  Optional[String]     $pod        = undef,
  Array[String]        $publish    = [],
  Hash[String, String] $secrets    = {},
  Array[String]        $tmpfs      = [],
  Array[String]        $volumes    = [],
) {
  unless $facts['is_container'] {
    require 'nest::base::containers'

    if $ensure == absent {
      service { "container-${name}":
        ensure => stopped,
        enable => false,
      }
      ->
      exec { "remove-container-${name}":
        command => "/usr/bin/podman container rm ${name.shellquote}",
        onlyif  => "/usr/bin/podman container exists ${name.shellquote}",
        before  => Nest::Lib::Pod[$pod],
      }

      file { "/etc/systemd/system/container-${name}.service":
        ensure => absent,
      }
      ~>
      nest::lib::systemd_reload { "container-${name}":
        require => Service["container-${name}"],
      }

      if $pod {
        exec { "regenerate-services-pod-${pod}-${name}":
          command     => "/usr/bin/podman generate systemd --files --name ${pod.shellquote}",
          cwd         => '/etc/systemd/system',
          refreshonly => true,
          subscribe   => Exec["remove-container-${name}"],
          notify      => Nest::Lib::Systemd_reload["container-${name}"],
        }
      }
    } else {
      if $pod and !empty($publish) {
        fail("Ports must be published on the pod '${pod}'")
      }

      case $ensure {
        'running': {
          $service_ensure = running
          $service_enable = true
        }

        'enabled': {
          $service_ensure = undef
          $service_enable = true
        }

        'present': {
          $service_ensure = undef
          $service_enable = undef
        }

        'disabled': {
          $service_ensure = undef
          $service_enable = false
        }

        'stopped': {
          $service_ensure = stopped
          $service_enable = false
        }

        default: {
          fail("Unhandled value for ensure: '${ensure}'")
        }
      }

      $dns_args = $dns ? {
        undef   => [],
        default => ["--dns=${dns}"],
      }

      $entrypoint_args = $entrypoint ? {
        undef   => [],
        default => ["--entrypoint=${entrypoint}"],
      }

      $env_args = $env.map |$e| {
        "--env=${e}"
      }

      $network_args = $network ? {
        undef   => [],
        default => ["--network=${network}"],
      }

      $pod_args = $pod ? {
        undef   => [],
        default => ["--pod=${pod}"],
      }

      $cap_add_args = $cap_add.map |$e| {
        "--cap-add=${e}"
      }

      $devices_args = $devices.map |$device| {
        "--device=${device}"
      }

      $publish_args = $publish.map |$e| {
        "--publish=${e}"
      }

      $secrets_args = $secrets.map |$secret_name, $secret_target| {
        "--secret=${secret_name},target=${secret_target},type=env"
      }

      $tmpfs_args = $tmpfs.map |$t| {
        "--tmpfs=${t}"
      }

      $volumes_args = $volumes.map |$volume| {
        "--volume=${volume}"
      }

      $podman_create_cmd = [
        '/usr/bin/podman', 'container', 'create',
        '--replace',
        $cap_add_args,
        $dns_args,
        $devices_args,
        $entrypoint_args,
        $env_args,
        $network_args,
        $pod_args,
        $publish_args,
        $secrets_args,
        $tmpfs_args,
        $volumes_args,
        "--label=nest.podman.version=${facts['podman_version']}",
        "--name=${name}",
        $image,
      ].flatten + $command

      $podman_create_str = "[${podman_create_cmd.join(' ')}]"
      $podman_inspect_create_command = [
        '/usr/bin/podman', 'container', 'inspect',
        '--format={{.Config.CreateCommand}}',
        $name,
      ]

      exec { "stop-container-${name}":
        command => "/bin/systemctl stop container-${name}",
        returns => [0, 5],
        unless  => "/usr/bin/test ${podman_create_str.shellquote} = \"`${podman_inspect_create_command.shellquote}`\"",
      }
      ~>
      exec { "create-container-${name}":
        command     => shellquote($podman_create_cmd),
        refreshonly => true,
        require     => Nest::Lib::Pod[$pod],
      }
      ~>
      exec { "generate-services-container-${name}":
        command     => "/usr/bin/podman generate systemd --files --name ${pick($pod, $name).shellquote}",
        cwd         => '/etc/systemd/system',
        refreshonly => true,
      }
      ~>
      nest::lib::systemd_reload { "container-${name}": }
      ->
      service { "container-${name}":
        ensure => $service_ensure,
        enable => $service_enable,
      }
    }
  }
}
