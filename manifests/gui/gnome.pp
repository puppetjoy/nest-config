class nest::gui::gnome {
  # Mutter has an unexpressed dependency on rst2man
  nest::lib::package { 'dev-python/docutils':
    ensure => installed,
  }
  ->
  nest::lib::package { 'gnome-base/gnome':
    ensure => installed,
  }
  ->
  service { 'gdm':
    enable => true,
  }
}
