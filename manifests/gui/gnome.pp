class nest::gui::gnome {
  nest::lib::package { 'gnome-base/gnome':
    ensure => installed,
  }
  ->
  service { 'gdm':
    enable => true,
  }
}
