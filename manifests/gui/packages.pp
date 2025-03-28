class nest::gui::packages {
  nest::lib::package { 'app-text/texlive':
    ensure => installed,
    use    => ['extra', 'xetex'],
  }

  nest::lib::package { 'net-dialup/minicom':
    ensure => installed,
  }
}
