class nest::gui::screenshots {
  nest::lib::package { 'media-gfx/flameshot':
    ensure => installed,
  }

  nest::lib::package { [
    'gui-apps/grim',
    'gui-apps/slurp',
    'gui-apps/swappy',
    'x11-misc/shutter',
    'kde-plasma/spectacle',
  ]:
    ensure => absent,
  }
}
