class nest::gui::packages {
  nest::lib::package { 'app-text/texlive':
    ensure => installed,
    use    => ['extra', 'xetex'],
  }

  nest::lib::package { [
    'media-gfx/gimp',
    'media-gfx/inkscape',
  ]:
    ensure => installed,
  }
}
