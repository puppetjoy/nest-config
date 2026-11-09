class nest::service::joyride_gateway (
  Boolean $https_enabled = false,
) {
  include 'apache::mod::proxy'
  include 'apache::mod::proxy_http'
  include 'apache::mod::headers'
  include 'apache::mod::rewrite'
  include 'apache::mod::ssl'

  $domain = 'joyridedc.com'
  $docroot = '/srv/www/joyridedc.com'
  $challenge_root = "${docroot}/.well-known/acme-challenge"
  $public_ip = ['45.77.156.204', '2001:19f0:1000:e1dc::204']

  file { $docroot:
    ensure => directory,
    owner  => $nest::user,
    group  => $nest::user,
    mode   => '0755',
  }

  file { "${docroot}/.well-known":
    ensure  => directory,
    owner   => $nest::user,
    group   => $nest::user,
    mode    => '0755',
    require => File[$docroot],
  }

  file { $challenge_root:
    ensure  => directory,
    owner   => $nest::user,
    group   => $nest::user,
    mode    => '0755',
    require => File["${docroot}/.well-known"],
  }

  $http_fragment = @("HTTP")
    RewriteEngine On
    RewriteCond %{HTTP_HOST} !^joyridedc\.com(?::80)?$ [NC]
    RewriteRule ^ - [F,L]
    RewriteCond %{REQUEST_URI} !^/\.well-known/acme-challenge/ [NC]
    RewriteRule ^ https://joyridedc.com%{REQUEST_URI} [R=301,L,NE]
    | HTTP

  apache::vhost { 'joyridedc.com-http':
    servername    => $domain,
    ip            => $public_ip,
    port          => 80,
    add_listen    => false,
    ssl           => false,
    docroot       => $docroot,
    docroot_owner => $nest::user,
    docroot_group => $nest::user,
    directories   => [
      {
        path    => $docroot,
        options => ['-Indexes', 'FollowSymLinks'],
      },
      {
        path    => $challenge_root,
        options => ['-Indexes', 'FollowSymLinks'],
        require => 'all granted',
      },
    ],
    custom_fragment => $http_fragment,
  }

  if $https_enabled {
    $https_fragment = @("HTTPS")
      RewriteEngine On
      RewriteCond %{HTTP_HOST} !^joyridedc\.com(?::443)?$ [NC,OR]
      RewriteCond %{SSL:SSL_TLS_SNI} !^joyridedc\.com$ [NC]
      RewriteRule ^ - [F,L]
      RewriteRule ^/(ops|admin|routing)(/|$) - [F,L,NC]
      | HTTPS

    apache::vhost { 'joyridedc.com-https':
      servername        => $domain,
      ip                => $public_ip,
      port              => 443,
      add_listen        => false,
      ssl               => true,
      ssl_cert          => '/etc/letsencrypt/live/joyridedc.com/fullchain.pem',
      ssl_key           => '/etc/letsencrypt/live/joyridedc.com/privkey.pem',
      ssl_proxyengine   => true,
      ssl_proxy_verify  => 'require',
      ssl_proxy_check_peer_name   => 'on',
      ssl_proxy_check_peer_expire => 'on',
      ssl_proxy_ca_cert => '/etc/ssl/certs/ca-certificates.crt',
      proxy_pass        => [
        {
          'path' => '/',
          'url'  => 'https://joyride.eyrie/',
        },
      ],
      proxy_preserve_host => false,
      proxy_add_headers   => false,
      request_headers     => [
        'unset Forwarded',
        'set X-Forwarded-Proto "https"',
        'set X-Forwarded-Host "joyridedc.com"',
        'set X-Forwarded-Port "443"',
        'set X-Forwarded-For expr=%{CONN_REMOTE_ADDR}',
        'set X-Real-IP expr=%{CONN_REMOTE_ADDR}',
      ],
      custom_fragment => $https_fragment,
      directories     => [
        {
          path    => $docroot,
          options => ['-Indexes', 'FollowSymLinks'],
        },
      ],
    }
  }
}
