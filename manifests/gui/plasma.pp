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

  # Plasma 6 no longer ships /etc/xdg/menus/applications.menu
  # It's now prefixed and called /etc/xdg/menus/plasma-applications.menu
  file { '/etc/environment.d/10-plasma.conf':
    ensure  => file,
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => "XDG_MENU_PREFIX=plasma-\n",
  }
}
