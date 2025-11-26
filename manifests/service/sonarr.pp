class nest::service::sonarr {
  # Required for media user
  include 'nest'

  nest::lib::srv { 'sonarr':
    mode  => '0755',
    owner => 'media',
    group => 'media',
  }
  ->
  file { '/srv/sonarr/config':
    ensure => directory,
    mode   => '0755',
    owner  => 'media',
    group  => 'media',
  }
  ->
  nest::lib::container { 'sonarr':
    image   => 'linuxserver/sonarr',
    dns     => '172.22.4.3',
    env     => ['PUID=1001', 'PGID=1001', 'TZ=America/New_York'],
    publish => ['8989:8989'],
    volumes => [
      '/srv/sonarr/config:/config',
      '/srv/nzbget/downloads:/downloads',
      '/nest/tv:/tv',
    ],
  }
}
