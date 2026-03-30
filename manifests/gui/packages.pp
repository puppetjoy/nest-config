class nest::gui::packages {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { [
        'media-gfx/gimp',
        'media-gfx/inkscape',
      ]:
        ensure => installed,
      }
    }

    'Darwin': {
      package { 'chatgpt':
        ensure => installed,
      }
    }
  }
}
