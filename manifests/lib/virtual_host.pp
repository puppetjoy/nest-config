define nest::lib::virtual_host (
  String                 $servername,
  String                 $docroot       = "/srv/www/${servername}",
  Hash[String, Any]      $extra_params  = {},
  Optional[Nest::IPList] $ip            = undef,
  Optional[Integer]      $port          = undef,
  Optional[String]       $priority      = undef,
  Array[String]          $serveraliases = [],
  Boolean                $ssl           = true,
  Boolean                $zfs_docroot   = true,
) {
  include 'nest::service::apache'

  $http_port = $port ? {
    undef   => 80,
    default => $port,
  }

  $https_port = $port ? {
    undef   => 443,
    default => $port,
  }

  $vhost_redirect_port = $port ? {
    undef   => '',
    default => ":${port}",
  }

  if $port and $nest::service::apache::manage_firewall {
    nest::lib::external_port { $name:
      port     => $port,
      protocol => tcp,
    }
  }

  ensure_resource('apache::listen', $http_port, {})

  if $docroot == "/srv/www/${servername}" {
    nest::lib::srv { "www/${servername}":
      zfs => $zfs_docroot,
    }
  }

  if $ssl {
    ensure_resource('apache::listen', $https_port, {})

    $vhost_name   = "${name}-ssl"
    $vhost_params = {
      'port'     => $https_port,
      'ssl'      => true,
      'ssl_cert' => "/etc/letsencrypt/live/${servername}/fullchain.pem",
      'ssl_key'  => "/etc/letsencrypt/live/${servername}/privkey.pem",
    }
    $vhost_redirect_proto = 'https'

    unless $port {
      apache::vhost { "${name}-redirect":
        priority        => $priority,
        servername      => $servername,
        serveraliases   => $serveraliases,
        ip              => $ip,
        port            => 80,
        add_listen      => false,
        docroot         => $docroot,
        docroot_owner   => $nest::user,
        docroot_group   => $nest::user,
        redirect_status => 'permanent',
        redirect_dest   => "https://${servername}/",
      }
    }
  } else {
    $vhost_name   = $name
    $vhost_params = {
      'port' => $http_port,
    }
    $vhost_redirect_proto = 'http'
  }

  apache::vhost { $vhost_name:
    priority      => $priority,
    servername    => $servername,
    ip            => $ip,
    add_listen    => false,
    docroot       => $docroot,
    docroot_owner => $nest::user,
    docroot_group => $nest::user,
    *             => $vhost_params + $extra_params,
  }

  unless empty($serveraliases) {
    apache::vhost { "${vhost_name}-redirect":
      priority        => $priority,
      servername      => $serveraliases[0],
      serveraliases   => $serveraliases[1, -1],
      ip              => $ip,
      add_listen      => false,
      docroot         => $docroot,
      docroot_owner   => $nest::user,
      docroot_group   => $nest::user,
      redirect_status => 'permanent',
      redirect_dest   => "${vhost_redirect_proto}://${servername}${vhost_redirect_port}/",
      *               => $vhost_params,
    }
  }
}
