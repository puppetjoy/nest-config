class nest::service::gitlab_runner (
  Integer             $concurrent = $nest::concurrency,
  String              $dns        = '172.22.4.3',
  Nest::ServiceEnsure $ensure     = running,
  Optional[String]    $host       = undef,
  Hash[String, Hash]  $instances  = {},
) inherits nest {
  $install = $uninstall = [Nest::Lib::Srv['gitlab-runner'], File['/usr/local/bin/gitlab-runner']]
  $run = $stop = Nest::Lib::Container['gitlab-runner']

  if $ensure == absent {
    $runner_ensure  = absent
    $runner_require = $stop
    $runner_before  = $uninstall
    $runner_notify  = undef
    $srv_notify     = undef
  } else {
    $runner_ensure  = present
    $runner_require = $install
    $runner_before  = $run

    if $facts['is_container'] {
      $runner_notify = undef
      $srv_notify    = undef
    } else {
      $runner_notify = Service['container-gitlab-runner']
      $srv_notify    = Exec['gitlab-runner-unregister-all']

      file_line { 'gitlab-runner-concurrent':
        path    => '/srv/gitlab-runner/config.toml',
        line    => "concurrent = ${concurrent}",
        match   => '^concurrent =',
        require => $run, # no restart required
      }
    }
  }

  nest::lib::srv { 'gitlab-runner':
    ensure => $runner_ensure,
    ignore => ['config.toml', '.runner_system_id'],
    purge  => true,
    notify => $srv_notify, # unregister purged instances
  }

  file { '/usr/local/bin/gitlab-runner':
    ensure  => $runner_ensure,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/scripts/gitlab-runner.sh',
    require => Class['nest::base::containers'],
  }

  if $runner_ensure == present and !$facts['is_container'] {
    $register_script_excludes = $instances.keys.map |$instance| {
      ['!', '-name', ".register-${instance}.sh"]
    }
    $stale_register_script_args = [
      '/usr/bin/find', '/srv/gitlab-runner', '-maxdepth', '1', '-type', 'f',
      '-name', '.register-*.sh', $register_script_excludes,
    ].flatten.shellquote

    exec { 'gitlab-runner-purge-stale-register-scripts':
      command => "${stale_register_script_args} -delete",
      onlyif  => "/usr/bin/test -n \"$(${stale_register_script_args} -print -quit)\"",
      require => Nest::Lib::Srv['gitlab-runner'],
      notify  => Exec['gitlab-runner-unregister-all'],
    }
  }

  $instances.each |$instance, $attributes| {
    nest::lib::gitlab_runner { $instance:
      require => $runner_require,
      before  => $runner_before,
      notify  => $runner_notify,
      *       => {
        dns    => $dns,
        ensure => $runner_ensure,
        host   => $host,
      } + $attributes,
    }
  }

  nest::lib::container { 'gitlab-runner':
    ensure  => $ensure,
    dns     => $dns,
    image   => 'gitlab/gitlab-runner:alpine-v19.0.0',
    volumes => [
      '/srv/gitlab-runner:/etc/gitlab-runner',
      '/run/podman/podman.sock:/var/run/docker.sock',
    ],
  }
}
