class nest::gui::packages {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { [
        'media-gfx/gimp',
        'media-gfx/inkscape',
      ]:
        ensure => installed,
      }

      nest::lib::package { 'net-im/telegram-desktop':
        ensure => installed,
        env    => {
          'FEATURES' => '-distcc',
        },
      }
    }

    'Darwin': {
      package { 'chatgpt':
        ensure => installed,
      }
    }
  }
}
