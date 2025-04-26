class nest::gui::plasma {
  nest::lib::package { 'kde-plasma/plasma-meta':
    ensure => installed,
    use    => ['-display-manager', '-firewall', '-networkmanager'],
  }

  # Don't build support for online services
  nest::lib::package { 'kde-plasma/spectacle':
    ensure => installed,
    use    => '-kipi',
  }

  nest::lib::package { [
    'kde-apps/ark',
    'kde-apps/dolphin',
    'kde-apps/ffmpegthumbs',
    'kde-apps/gwenview',
    'kde-apps/kdialog',
    'kde-apps/kwrite',
    'kde-apps/okular',
  ]:
    ensure => installed,
  }
}
