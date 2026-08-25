class nest::service::plex {
  nest::lib::container { 'plex':
    image   => 'plexinc/pms-docker',
    env     => ['PLEX_UID=1001', 'PLEX_GID=1001', 'TZ=America/New_York'],
    network => 'host',
    tmpfs   => ['/transcode:rw,mode=1777'],
    volumes => [
      '/srv/plex/config:/config',
      '/nest/movies:/movies:ro',
      '/nest/tv:/tv:ro',
    ],
  }

  nest::lib::external_service { 'plex': }
}
