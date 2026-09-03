class nest::gui::environment {
  # GNOME sessions started as systemd user services inherit environment.d.
  # Keep this off workstations, whose XMonad/Sway wrappers deliberately own
  # QT_SCALE_FACTOR and QT_FONT_DPI instead.
  file {
    '/etc/environment.d':
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    ;

    '/etc/environment.d/60-nest-gui.conf':
      ensure  => file,
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => "QT_AUTO_SCREEN_SCALE_FACTOR=1\n",
    ;
  }
}
