class nest::gui::media {
  nest::lib::package { [
    'media-sound/playerctl',
    'media-video/mpv',
  ]:
    ensure => installed,
  }

  if 'vaapi' in $facts['portage_use'].split(' ') {
    nest::lib::package { 'media-video/libva-utils':
      ensure => installed,
    }

    if 'intel' in $facts['portage_video_cards'].split(' ') {
      nest::lib::package { 'media-libs/libva-intel-driver':
        ensure => installed,
      }
    }
  }
}
