class nest::gui::gnome {
  # Mutter has an unexpressed dependency on rst2man
  nest::lib::package { 'dev-python/docutils':
    ensure => installed,
  }
  ->
  nest::lib::package { 'gnome-base/gnome':
    ensure => installed,
  }

  $keyboard_source = $nest::dvorak ? {
    true    => 'us+dvorak',
    default => 'us',
  }

  $xkb_options = $nest::swap_alt_win ? {
    true    => "['ctrl:nocaps', 'altwin:swap_alt_win']",
    default => "['ctrl:nocaps']",
  }

  $input_sources_content = @("END")
    [org/gnome/desktop/input-sources]
    sources=[('xkb', '${keyboard_source}')]
    xkb-options=${xkb_options}
    | END

  $user_profile_content = @("END")
    user-db:user
    system-db:local
    | END

  $gdm_profile_content = @("END")
    user-db:user
    system-db:gdm
    file-db:/usr/share/gdm/greeter-dconf-defaults
    | END

  exec { 'dconf-update':
    command     => '/usr/bin/dconf update',
    refreshonly => true,
    require     => Nest::Lib::Package['gnome-base/gnome'],
  }

  file {
    default:
      owner   => 'root',
      group   => 'root',
      require => Nest::Lib::Package['gnome-base/gnome'],
      notify  => Exec['dconf-update'],
    ;

    '/etc/dconf':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/db':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/db/gdm.d':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/db/gdm.d/00-input-sources':
      mode    => '0644',
      content => $input_sources_content,
    ;

    '/etc/dconf/db/local.d':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/db/local.d/00-input-sources':
      mode    => '0644',
      content => $input_sources_content,
    ;

    '/etc/dconf/profile':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/profile/gdm':
      mode    => '0644',
      content => $gdm_profile_content,
    ;

    '/etc/dconf/profile/user':
      mode    => '0644',
      content => $user_profile_content,
    ;
  }

  service { 'gdm':
    enable  => true,
    require => Nest::Lib::Package['gnome-base/gnome'],
  }
}
