class nest::gui::media {
  $vaapi_enabled = 'vaapi' in $facts['portage_use'].split(' ')
  $intel_enabled = 'intel' in $facts['portage_video_cards'].split(' ')

  nest::lib::package { [
    'media-sound/playerctl',
    'media-video/mpv',
  ]:
    ensure => installed,
  }

  nest::lib::package { 'media-video/libva-utils':
    ensure => $vaapi_enabled ? {
      true    => installed,
      default => absent,
    },
  }

  nest::lib::package { 'media-libs/libva-intel-driver':
    ensure => ($vaapi_enabled and $intel_enabled) ? {
      true    => installed,
      default => absent,
    },
  }
}
