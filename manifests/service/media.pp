# Media applications live in Eyrie; historical Podman data/containers stay intact.
class nest::service::media {
  unless $facts['is_container'] {
    service { ['container-nzbget', 'container-ombi', 'container-plex', 'container-radarr', 'container-sonarr']:
      ensure => stopped,
      enable => false,
    }
  }
}
