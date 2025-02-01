class nest::service::gitlab (
  String            $external_name,
  Optional[String]  $registry_external_name = undef,
  Boolean           $https                  = false,
  String            $image                  = 'gitlab/gitlab-ce',
  Stdlib::Port      $ssh_port               = 22,
  Stdlib::Port      $web_port               = 80,
  Stdlib::Port      $registry_port          = 5050,
  Optional[Integer] $default_theme          = undef,
  Optional[String]  $gmail_username         = undef,
  Optional[String]  $gmail_password         = undef,
  Integer           $puma_workers           = $nest::concurrency,
) inherits nest {
  if $https {
    $external_url = "https://${external_name}"

    if $registry_external_name {
      $registry_url = "https://${registry_external_name}"
    }
  } else {
    $external_url = $web_port ? {
      80      => "http://${external_name}",
      default => "http://${external_name}:${http_port}",
    }

    if $registry_external_name {
      $registry_url = $registry_port ? {
        5050    => "http://${registry_external_name}",
        default => "http://${registry_external_name}:${registry_port}",
      }
    }
  }

  $publish = [
    "${web_port}:${web_port}",

    $ssh_port ? {
      22      => '2222:22',
      default => "${ssh_port}:22",
    },

    $registry_external_name ? {
      undef   => [],
      default => "${registry_port}:${registry_port}",
    },
  ].flatten

  nest::lib::srv { 'gitlab': }
  ->
  file {
    default:
      owner => 'root',
      group => 'root',
    ;

    '/srv/gitlab/gitlab.rb':
      mode      => '0600',
      content   => template('nest/gitlab/gitlab.rb.erb'),
      show_diff => false,
    ;

    [
      '/srv/gitlab/config',
      '/srv/gitlab/logs',
      '/srv/gitlab/data',
    ]:
      ensure => directory,
    ;
  }
  ->
  nest::lib::container { 'gitlab':
    image   => $image,
    cap_add => ['SYS_CHROOT'],
    env     => ["GITLAB_OMNIBUS_CONFIG=from_file('/omnibus_config.rb')"],
    publish => $publish,
    volumes => [
      '/srv/gitlab/gitlab.rb:/omnibus_config.rb:ro',
      '/srv/gitlab/config:/etc/gitlab',
      '/srv/gitlab/logs:/var/log/gitlab',
      '/srv/gitlab/data:/var/opt/gitlab',
    ],
  }

  unless $facts['is_container'] {
    File['/srv/gitlab/gitlab.rb']
    ~> Service['container-gitlab']
  }
}
