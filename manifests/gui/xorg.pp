class nest::gui::xorg {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { 'x11-base/xorg-server':
        ensure => installed,
      }

      file { [
        '/etc/X11',
        '/etc/X11/xorg.conf.d',
      ]:
        ensure  => directory,
        mode    => '0755',
        owner   => 'root',
        group   => 'root',
        require => Nest::Lib::Package['x11-base/xorg-server'],
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

      $monitor_layout       = $nest::monitor_layout
      $primary_monitor      = $nest::primary_monitor
      $monitors_conf_ensure = $monitor_layout ? {
        []      => 'absent',
        default => 'present',
      }

      file { '/etc/X11/xorg.conf.d/10-monitors.conf':
        ensure  => $monitors_conf_ensure,
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => template('nest/xorg/monitors.conf.erb'),
      }

      file { '/etc/X11/xorg.conf.d/10-libinput.conf':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => template('nest/xorg/libinput.conf.erb'),
      }

      file { '/etc/X11/Xresources':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => "Xcursor.theme: breeze_cursors\nXcursor.size: ${nest::cursor_size}\nXft.dpi: ${nest::dpi}\n",
      }

      nest::lib::package { [
        'x11-apps/mesa-progs',
        'x11-apps/xev',
        'x11-apps/xhost',
        'x11-apps/xinput',
        'x11-apps/xkill',
        'x11-apps/xlogo',
        'x11-apps/xmodmap',
        'x11-apps/xrandr',
        'x11-apps/xsetroot',
        'x11-apps/xwininfo',
        'x11-misc/xdotool',
      ]:
        ensure => installed,
      }


      # Load i2c-dev for controlling monitors
      file { '/etc/modules-load.d/i2c-dev.conf':
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        content => "i2c-dev\n",
      }

      nest::lib::package { 'app-misc/ddcutil':
        ensure => installed,
      }


      # XXX cleanup
      file { [
        '/etc/X11/xinit/xinitrc.d/99-setxkbmap',
        '/etc/X11/xinit/xinitrc.d/10-scaling',
      ]:
        ensure => absent,
      }
    }

    'windows': {
      package { [
        'xorg-server',
        'xset',
      ]:
        ensure   => installed,
        provider => 'cygwin',
      }

      file { 'C:/ProgramData/Microsoft/Windows/Start Menu/Programs/Cygwin-X':
        ensure => directory,
        mode   => '0755',
      }
      ->
      package { 'xinit':
        ensure   => installed,
        provider => 'cygwin',
      }
      ->
      file { 'C:/ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/XWin Server.lnk':
        source => 'C:/ProgramData/Microsoft/Windows/Start Menu/Programs/Cygwin-X/XWin Server.lnk',
      }

      file { 'C:/tools/cygwin/etc/X11/Xresources':
        mode    => '0644',
        owner   => 'Administrators',
        group   => 'None',
        content => "Xft.dpi: ${nest::dpi}\n",
        require => Package['xinit'],
      }
    }
  }
}
