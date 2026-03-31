class nest::gui::media {
  nest::lib::package { [
    'media-sound/playerctl',
    'media-video/mpv',
  ]:
    ensure => installed,
  }

  $vaapi_enabled = 'vaapi' in $facts['portage_use'].split(' ')
  $libva_utils_ensure = $vaapi_enabled ? {
    true    => installed,
    default => absent,
  }

  nest::lib::package { 'media-video/libva-utils':
    ensure => $libva_utils_ensure,
  }

  $intel_enabled = 'intel' in $facts['portage_video_cards'].split(' ')
  $libva_intel_driver_ensure = ($vaapi_enabled and $intel_enabled) ? {
    true    => installed,
    default => absent,
  }

  nest::lib::package { 'media-libs/libva-intel-driver':
    ensure => $libva_intel_driver_ensure,
  }
}
