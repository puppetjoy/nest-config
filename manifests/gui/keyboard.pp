class nest::gui::keyboard {
  file { [
    '/etc/X11',
    '/etc/X11/xorg.conf.d',
  ]:
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
  }

  $keyboard_layout = 'us'

  if $nest::dvorak {
    $keyboard_variant = 'dvorak'
  }

  $keyboard_options = $nest::swap_alt_win ? {
    true    => 'ctrl:nocaps,terminate:ctrl_alt_bksp,altwin:swap_alt_win',
    default => 'ctrl:nocaps,terminate:ctrl_alt_bksp',
  }

  # This file is ordinarily managed by localectl.
  # This tries to be compatible.
  file { '/etc/X11/xorg.conf.d/00-keyboard.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => template('nest/xorg/keyboard.conf.erb'),
  }
}
