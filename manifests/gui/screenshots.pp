class nest::gui::screenshots {
  nest::lib::package { [
    'gui-apps/grim',
    'gui-apps/slurp',
    'gui-apps/swappy',
    'media-gfx/imagemagick',
    'x11-misc/shutter',
    'x11-misc/xclip',
  ]:
    ensure => installed,
  }

  nest::lib::package { 'kde-plasma/spectacle':
    ensure => absent,
  }
}
