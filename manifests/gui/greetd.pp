class nest::gui::greetd {
  $environments = $nest::autologin ? {
    'sway'  => "sway\nxmonad\n",
    default => "xmonad\nsway\n",
  }

  $autologin_session = $nest::autologin ? {
    true    => 'xmonad',
    false   => undef,
    default => $nest::autologin,
  }

  nest::lib::package { [
    'gui-libs/greetd',
    'gui-apps/gtkgreet',
  ]:
    ensure => installed,
  }
  ->
  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/greetd/config.toml':
      content => epp('nest/greetd/config.toml.epp', {
        'autologin_session' => $autologin_session,
      }),
    ;

    '/etc/greetd/sway-config':
      source => 'puppet:///modules/nest/greetd/sway-config',
    ;

    '/etc/greetd/environments':
      content => $environments,
    ;
  }
  ->
  service { 'greetd':
    enable => true,
  }
}
