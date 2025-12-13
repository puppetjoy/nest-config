class nest::service::puppet (
  Sensitive $puppetboard_secret_key,
  Sensitive $r10k_deploy_key,
) {
  Nest::Lib::Srv {
    mode  => '0755',
    owner => 'root',
    group => 'root',
  }

  nest::lib::srv {
    'puppet':
      # use defaults
    ;

    'puppet/bin':
      zfs     => false,
      require => Nest::Lib::Srv['puppet'],
    ;

    'puppet/code':
      require => Nest::Lib::Srv['puppet'],
    ;
  }

  nest::lib::pod { 'puppet':
    dns     => '172.22.4.3',  # PuppetDB init checks for 'puppet' in DNS
    publish => [
      '8140:8140',  # Puppet Server
      '8080:8080',  # PuppetDB dashboard
      '8081:8081',  # PuppetDB API
      '8180:80',    # Puppetboard
    ],
  }

  nest::lib::external_service { 'puppetmaster': }


  #
  # Puppet Server
  #
  nest::lib::srv { 'puppet/puppetserver':
    require => Nest::Lib::Srv['puppet'],
  }
  ->
  file {
    '/srv/puppet/puppetserver/init':
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    ;

    '/srv/puppet/puppetserver/init/10-set-main-environment.sh':
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
      source => 'puppet:///modules/nest/puppet/set-main-environment.sh',
    ;

    '/srv/puppet/puppetserver/config':
      ensure => directory,
    ;
  }
  ->
  nest::lib::container { 'puppetserver':
    pod     => 'puppet',
    image   => 'registry.gitlab.joyfullee.me/nest/forks/container-puppetserver:8.7.0',
    env     => [
      'PUPPETSERVER_ENVIRONMENT_TIMEOUT=0',
      'PUPPETSERVER_HOSTNAME=puppet',
      'DNS_ALT_NAMES=puppet.nest,puppet.joyfullee.me',
      'CA_ALLOW_SUBJECT_ALT_NAMES=true',
      'PUPPETDB_SERVER_URLS=https://puppet:8081',
    ],
    volumes => [
      '/etc/eyaml:/etc/eyaml:ro',
      '/srv/puppet/puppetserver/init:/docker-custom-entrypoint.d',
      '/srv/puppet/code:/etc/puppetlabs/code:ro',
      '/srv/puppet/puppetserver/config:/etc/puppetlabs/puppet',
      '/srv/puppet/puppetserver/ca:/etc/puppetlabs/puppetserver/ca',
      '/srv/puppet/r10k/cache:/var/cache/r10k:ro',
    ],
    require => Nest::Lib::Srv['puppet/code'],
  }

  exec { 'make-eyaml-key-puppet-readable':
    command => '/usr/sbin/setfacl -m user:999:r /etc/eyaml/keys/private_key.pkcs7.pem',
    unless  => '/usr/sbin/getfacl /etc/eyaml/keys/private_key.pkcs7.pem | /bin/grep "^user:999:r--"',
    require => File['/etc/eyaml/keys/private_key.pkcs7.pem'],
  }

  #
  # Postgres for PuppetDB
  #
  nest::lib::srv { 'puppet/postgres':
    require => Nest::Lib::Srv['puppet'],
  }
  ->
  file { '/srv/puppet/postgres/data':
    ensure => directory,
  }
  ->
  nest::lib::container { 'puppet-postgres':
    pod     => 'puppet',
    image   => 'postgres:16',
    env     => ['POSTGRES_USER=puppetdb', 'POSTGRES_PASSWORD=puppetdb'],
    volumes => ['/srv/puppet/postgres/data:/var/lib/postgresql/data'],
  }


  #
  # PuppetDB
  #
  nest::lib::srv { 'puppet/puppetdb':
    require => Nest::Lib::Srv['puppet'],
  }
  ->
  file { '/srv/puppet/puppetdb/data':
    ensure => directory,
  }
  ->
  nest::lib::container { 'puppetdb':
    pod     => 'puppet',
    image   => 'registry.gitlab.joyfullee.me/nest/forks/container-puppetdb:8.8.1',
    env     => [
      'DNS_ALT_NAMES=puppet,puppetdb.nest',
      'PUPPETDB_POSTGRES_HOSTNAME=localhost',
      'PUPPETDB_NODE_TTL=0d',
    ],
    volumes => ['/srv/puppet/puppetdb/data:/opt/puppetlabs/server/data/puppetdb'],
  }


  #
  # Puppetboard
  #
  nest::lib::container { 'puppetboard':
    pod   => 'puppet',
    image => 'ghcr.io/voxpupuli/puppetboard:5.4.0',
    env   => [
      'PUPPETDB_HOST=puppet',
      'ENABLE_CATALOG=True',
      'DEFAULT_ENVIRONMENT=main',
      'UNRESPONSIVE_HOURS=8760', # 1 year
      "SECRET_KEY=${puppetboard_secret_key.unwrap}",
    ],
  }


  #
  # R10k
  #
  nest::lib::srv { 'puppet/r10k':
    require => Nest::Lib::Srv['puppet'],
  }
  ->
  file {
    default:
      owner => 'root',
      group => 'root',
    ;

    [
      '/srv/puppet/r10k/cache',
      '/srv/puppet/r10k/config',
    ]:
      ensure => directory,
      mode   => '0755',
    ;

    '/srv/puppet/r10k/config/r10k.yaml':
      mode   => '0644',
      source => 'puppet:///modules/nest/puppet/r10k.yaml',
    ;

    '/srv/puppet/r10k/config/id_rsa':
      mode    => '0600',
      content => $r10k_deploy_key,
    ;
  }
  ->
  file { '/srv/puppet/bin/r10k':
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
    source => 'puppet:///modules/nest/puppet/r10k.sh',
  }
}
