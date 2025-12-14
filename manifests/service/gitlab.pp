class nest::service::gitlab (
  Optional[String]    $external_name          = undef,
  Optional[String]    $registry_external_name = undef,
  Boolean             $https                  = false,
  String              $image                  = 'gitlab/gitlab-ce',
  Stdlib::Port        $ssh_port               = 22,
  Stdlib::Port        $web_port               = 80,
  Stdlib::Port        $registry_port          = 5050,
  Optional[Integer]   $default_theme          = undef,
  Optional[String]    $gmail_username         = undef,
  Optional[String]    $gmail_password         = undef,
  Integer             $puma_workers           = $nest::concurrency,
  Optional[Sensitive] $ssh_private_key        = undef,
) inherits nest {
  if defined(Class['nest::kubernetes']) {
    $ssh_load_balancer_ip = lookup('nest::host_records')["ssh.${nest::kubernetes::fqdn}"]
    $ssh_private_key_base64 = base64('encode', $ssh_private_key.unwrap)

    if $nest::kubernetes::service == $nest::kubernetes::main_service {
      $bucket_user = nest::kubernetes::bucket_user(lookup('ceph_object_store'), $nest::kubernetes::service, lookup('ceph_namespace'))

      $artifacts_bucket_config   = nest::kubernetes::bucket_config("${nest::kubernetes::service}-artifacts")
      $backups_bucket_config     = nest::kubernetes::bucket_config("${nest::kubernetes::service}-backups")
      $backups_tmp_bucket_config = nest::kubernetes::bucket_config("${nest::kubernetes::service}-backups-tmp")
      $lfs_bucket_config         = nest::kubernetes::bucket_config("${nest::kubernetes::service}-lfs")
      $packages_bucket_config    = nest::kubernetes::bucket_config("${nest::kubernetes::service}-packages")
      $registry_bucket_config    = nest::kubernetes::bucket_config("${nest::kubernetes::service}-registry")
      $uploads_bucket_config     = nest::kubernetes::bucket_config("${nest::kubernetes::service}-uploads")

      $endpoint = $bucket_user['Endpoint']
      $host_base = $endpoint.regsubst('^https?://', '')

      # Expects s3cmd config
      # see: https://docs.gitlab.com/charts/backup-restore/#backups-to-s3
      # example: https://docs.gitlab.com/charts/advanced/external-object-storage/#backups-storage-example
      $backups_config = @("S3CFG")
        [default]
        access_key = ${bucket_user['AccessKey']}
        secret_key = ${bucket_user['SecretKey']}
        host_base = ${host_base}
        host_bucket = %(bucket)s.${host_base}
        use_https = False
        | S3CFG

      # Object Storage connection for GitLab Rails
      # see: https://docs.gitlab.com/charts/charts/globals/#connection
      # example: https://gitlab.com/gitlab-org/charts/gitlab/-/blob/master/examples/objectstorage/rails.s3.yaml
      $object_store_connection = @("YAML")
        provider: AWS
        aws_access_key_id: ${bucket_user['AccessKey']}
        aws_secret_access_key: ${bucket_user['SecretKey']}
        endpoint: ${endpoint}
        | YAML

      # Registry object storage config
      # see: https://docs.gitlab.com/charts/charts/registry/#storage
      # example: https://gitlab.com/gitlab-org/charts/gitlab/-/blob/master/examples/objectstorage/registry.s3.yaml
      $registry_config = @("YAML")
        s3:
          accesskey: ${bucket_user['AccessKey']}
          secretkey: ${bucket_user['SecretKey']}
          region: not-important
          regionendpoint: ${endpoint}
          bucket: ${registry_bucket_config['BUCKET_NAME']}
          chunksize: 67108864 # 64 MiB
          secure: false
        | YAML

      $backups_config_base64          = base64('encode', $backups_config)
      $object_store_connection_base64 = base64('encode', $object_store_connection)
      $registry_config_base64         = base64('encode', $registry_config)

      if $gmail_password {
        $gmail_password_base64 = base64('encode', $gmail_password)
      } else {
        $gmail_password_base64 = undef
      }
    }
  } else {
    if empty($external_name) {
      fail('The external name must be set for the GitLab service')
    }

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
}
