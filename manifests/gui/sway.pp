class nest::gui::sway {
  nest::lib::package { 'gui-wm/sway':
    ensure => installed,
    use    => ['-swaybar', 'wallpapers'],
  }

  nest::lib::package { [
    'gui-apps/waybar',
    'gui-apps/wl-clipboard',  # for tmux-yank
    'gui-apps/wtype',         # for simulating keyboard input
  ]:
    ensure => installed,
  }

  # Sway will scale the display to our gui_scaling_factor, but we need
  # to change the DPI to effect our text_scaling_factor
  $gui_scaling_factor  = $nest::gui_scaling_factor
  $text_scaling_factor = $nest::text_scaling_factor
  $dpi       = Integer(inline_template('<%= ((@text_scaling_factor / @gui_scaling_factor) * 96.0).round %>'))
  $dpi_scale = Float(inline_template('<%= (@text_scaling_factor / @gui_scaling_factor).round(3) %>'))

  # HW cursor doesn't work on VMware
  $no_hardware_cursors = $facts['virtual'] ? {
    'vmware' => 1,
    default  => 0,
  }

  $sway_wrapper_content = @("END_WRAPPER"/$)
    #!/bin/bash
    export GDK_DPI_SCALE=${dpi_scale}
    export QT_FONT_DPI=${dpi}
    export WLR_LIBINPUT_NO_DEVICES=1
    export WLR_NO_HARDWARE_CURSORS=${no_hardware_cursors}
    export XCURSOR_SIZE=24
    export XDG_SESSION_DESKTOP=sway
    export XDG_SESSION_TYPE=wayland
    exec "\$SHELL" -c "systemd-cat --identifier=sway /usr/bin/sway \${*@Q}"
    | END_WRAPPER

  file { '/usr/local/bin/sway':
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => $sway_wrapper_content,
  }

  $xresources_content = @("XRESOURCES")
    Xft.dpi: ${dpi}
    | XRESOURCES

  file { '/etc/sway/Xresources':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $xresources_content,
    require => Nest::Lib::Package['gui-wm/sway'],
  }

  $xkb_variant = $nest::dvorak ? {
    true    => "input type:keyboard xkb_variant dvorak\n",
    default => '',
  }

  $xkb_options = $nest::swap_alt_win ? {
    true    => 'input type:keyboard xkb_options ctrl:nocaps,altwin:swap_alt_win',
    default => 'input type:keyboard xkb_options ctrl:nocaps',
  }

  $cursor_conf = @("CURSOR_CONF"/$)
    seat seat0 xcursor_theme breeze_cursors 24
    | CURSOR_CONF

  $input_conf = @("INPUT_CONF")
    input type:keyboard xkb_layout us
    ${xkb_variant}${xkb_options}
    input type:touchpad tap enabled
    | INPUT_CONF

  # XXX: According to sway-output(5), this needs to account for scaling
  $monitors_conf = $nest::monitor_layout.reduce('') |$memo, $monitor| {
    if $monitor =~ /([^@]+)@(\d+)$/ {
      "${memo}output ${1} position ${2} 0\n"
    } else {
      $memo
    }
  }

  $output_conf = @("OUTPUT_CONF")
    output * scale ${nest::gui_scaling_factor}
    output * subpixel rgb
    ${monitors_conf}
    | - OUTPUT_CONF

  file {
    default:
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      require => Nest::Lib::Package['gui-wm/sway'],
    ;

    '/etc/sway/config':
      content => "include /etc/sway/config.d/*\n",
    ;

    '/etc/sway/config.d':
      ensure => directory,
    ;

    '/etc/sway/config.d/10-cursor':
      content => $cursor_conf,
    ;

    '/etc/sway/config.d/10-input':
      content => $input_conf,
    ;

    '/etc/sway/config.d/10-output':
      content => $output_conf,
    ;

    # XXX cleanup
    '/etc/sway/config.d/10-xwayland':
      ensure => absent,
    ;
  }
}
