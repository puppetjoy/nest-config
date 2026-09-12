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
    systemd::timer_wrapper { 'podman-build-cache-prune':
      ensure                 => present,
      command                => '/usr/bin/podman container prune --force --filter until=720h',
      on_calendar            => 'daily',
      service_overrides      => {
        'ExecStart' => [
          '/usr/bin/podman container prune --force --filter until=720h',
          '/usr/bin/podman image prune --force --filter until=720h',
        ],
      },
      service_unit_overrides => {
        'Description' => 'Prune stale Podman build containers and dangling images',
      },
      timer_overrides        => {
        'Persistent'         => true,
        'RandomizedDelaySec' => '1h',
      },
      timer_unit_overrides   => {
        'Description' => 'Daily stale Podman build cache pruning',
      },
      require                => Class['nest::base::containers'],
    }
  } elsif !$facts['is_container'] {
    systemd::timer_wrapper { 'podman-build-cache-prune':
      ensure => absent,
    }
  }

  if $runner_ensure == present and !$facts['is_container'] {
    exec { 'gitlab-runner-reconcile-invalid':
      command => '/bin/true',
      unless  => '/usr/local/bin/gitlab-runner verify',
      require => $install,
      notify  => Exec['gitlab-runner-unregister-all'],
    }

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
    $registration_token_key = $attributes['registration_token_key']
    if $registration_token_key {
      $runner_attributes = $attributes.filter |$key, $_value| {
        $key != 'registration_token_key'
      } + {
        'registration_token' => lookup($registration_token_key),
      }
    } else {
      $runner_attributes = $attributes
    }

    nest::lib::gitlab_runner { $instance:
      require => $runner_require,
      before  => $runner_before,
      notify  => $runner_notify,
      *       => {
        dns    => $dns,
        ensure => $runner_ensure,
        host   => $host,
      } + $runner_attributes,
    }
  }

  nest::lib::container { 'gitlab-runner':
    ensure  => $ensure,
    dns     => $dns,
    image   => 'gitlab/gitlab-runner:alpine-v19.3.2',
    volumes => [
      '/etc/ssl/certs/ca-certificates.crt:/etc/ssl/certs/ca-certificates.crt:ro',
      '/srv/gitlab-runner:/etc/gitlab-runner',
      '/run/podman/podman.sock:/var/run/docker.sock',
    ],
  }
}
