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
    ignore => ['config.toml', '.*'],
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

  $instances.each |$instance, $attributes| {
    nest::lib::gitlab_runner { $instance:
      require => $runner_require,
      before  => $runner_before,
      notify  => $runner_notify,
      *       => {
        dns  => $dns,
        host => $host,
      } + $attributes + {
        ensure => $runner_ensure,
      },
    }
  }

  # Use Apline image like official GitLab image
  # See: https://gitlab.alpinelinux.org/alpine/infra/docker/gitlab-runner/-/blob/master/Dockerfile
  # See: https://gitlab.com/gitlab-org/gitlab-runner/-/blob/main/dockerfiles/runner/ubuntu/Dockerfile
  nest::lib::container { 'gitlab-runner':
    ensure     => $ensure,
    dns        => $dns,
    image      => 'alpinelinux/gitlab-runner',
    entrypoint => '/usr/bin/gitlab-runner', # avoid entrypoint that manages registrations
    command    => ['run', '--user=gitlab-runner', '--working-directory=/var/lib/gitlab-runner'],
    volumes    => [
      '/srv/gitlab-runner:/etc/gitlab-runner',
      '/run/podman/podman.sock:/var/run/docker.sock',
    ],
  }
}
