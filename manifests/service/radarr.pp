class nest::service::radarr {
  # Required for media user
  include 'nest'

  nest::lib::srv { 'radarr':
    mode  => '0755',
    owner => 'media',
    group => 'media',
  }
  ->
  file { '/srv/radarr/config':
    ensure => directory,
    mode   => '0755',
    owner  => 'media',
    group  => 'media',
  }
  ->
  nest::lib::container { 'radarr':
    image   => 'linuxserver/radarr',
    dns     => '172.22.4.3',
    env     => ['PUID=1001', 'PGID=1001', 'TZ=America/New_York'],
    publish => ['7878:7878'],
    volumes => [
      '/srv/radarr/config:/config',
      '/srv/nzbget/downloads:/downloads',
      '/nest/movies:/movies',
    ],
  }
}
