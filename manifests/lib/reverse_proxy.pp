define nest::lib::reverse_proxy (
  Variant[String, Array[String]] $destination,
  Boolean                  $encoded_slashes = false,
  Hash[String, Any]        $extra_params    = {},
  Optional[Nest::IPList]   $ip              = undef,
  Optional[Integer]        $port            = undef,
  Boolean                  $preserve_host   = false,
  Optional[String]         $priority        = undef,
  Boolean                  $proxy_ssl       = false,
  String                   $servername      = $name,
  Array[String]            $serveraliases   = [],
  Boolean                  $serve_local     = false,
  Boolean                  $ssl             = true,
  Optional[Integer]        $timeout         = undef,
  Variant[Boolean, String] $websockets      = false,
  String                   $docroot         = "/srv/www/${servername}",
) {
  include 'apache::mod::proxy'

  if $proxy_ssl {
    $http_proto = 'https'
    $ws_proto   = 'wss'
  } else {
    $http_proto = 'http'
    $ws_proto   = 'ws'
  }

  if $destination =~ String {
    $url      = "${http_proto}://${destination}/"
    $balancer = ''
  } else {
    include 'apache::mod::proxy_balancer'
    apache::mod { 'lbmethod_byrequests': } # apache::mod::lbmethod_byrequests has a broken version check

    $url      = "balancer://${name}/"
    $members  = $destination.map |$d| { "    BalancerMember ${http_proto}://${d}" }
    $balancer = @("BALANCER")
      <Proxy balancer://${name}>
      ${members.join("\n")}
        </Proxy>

        
      |- BALANCER
  }

  if $encoded_slashes {
    $proxy_pass_keywords = ['nocanon']
    $allow_encoded_slashes = on
  } else {
    $proxy_pass_keywords = []
    $allow_encoded_slashes = off
  }

  if $serve_local {
    $proxy_path     = '/_backend_/'
    $proxy_rewrites = {
      rewrites => [
        { 'rewrite_base' => '/' },
        { 'rewrite_rule' => ['^$ /_backend_/ [L]'] },
        {
          'rewrite_cond' => [
            '%{REQUEST_FILENAME} !-f',
            '%{REQUEST_FILENAME} !-d',
          ],
          'rewrite_rule' => ['^(.*) /_backend_/$1 [L]'],
        },
      ],
    }
  } else {
    $proxy_path     = '/'
    $proxy_rewrites = {}
  }

  if $timeout {
    $proxy_params = { 'timeout' => $timeout }
  } else {
    $proxy_params = {}
  }

  $proxy_pass = [{
    'path'     => $proxy_path,
    'url'      => $url,
    'keywords' => $proxy_pass_keywords,
    'params'   => $proxy_params,
  }]

  $directories = [
    {
      'path'     => $docroot,
      'options'  => ['Indexes', 'FollowSymLinks', 'MultiViews'],
    } + $proxy_rewrites,
  ]

  if $websockets {
    include 'apache::mod::proxy_wstunnel'

    $wsdestination = $websockets ? {
      String  => $websockets,
      default => $destination,
    }

    $websocket_rewrites = [{
      'rewrite_cond' => ['%{HTTP:Upgrade} =websocket [NC]'],
      'rewrite_rule' => ["^/(.*)$ ${ws_proto}://${wsdestination}/\$1 [P,L]"],
    }]
  } else {
    $websocket_rewrites = []
  }

  $certbot_exception = @(EOT)
    <Location "/.well-known">
        AllowOverride None
        Require all granted
        ProxyPass !
      </Location>
    | EOT

  nest::lib::virtual_host { $name:
    docroot       => $docroot,
    priority      => $priority,
    servername    => $servername,
    serveraliases => $serveraliases,
    ip            => $ip,
    port          => $port,
    ssl           => $ssl,
    zfs_docroot   => false,
    extra_params  => {
      'allow_encoded_slashes' => $allow_encoded_slashes,
      'directories'           => $directories,
      'proxy_pass'            => $proxy_pass,
      'proxy_preserve_host'   => $preserve_host,
      'rewrites'              => $websocket_rewrites,
      'ssl_proxyengine'       => $proxy_ssl,
      'custom_fragment'       => "${balancer}${certbot_exception}",
    } + $extra_params,
  }
}
