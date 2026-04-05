class nest::gui::gnome {
  contain nest::gui::keyboard

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

  nest::lib::dconf { 'input-sources':
    settings => {
      'org/gnome/desktop/input-sources' => {
        'sources'     => "[('xkb', '${keyboard_source}')]",
        'xkb-options' => $xkb_options,
      },
    },
    locks    => true,
  }

  $accountsservice_icon = "/var/lib/AccountsService/icons/${nest::user}"

  $accountsservice_user_content = @("END")
    [User]
    Icon=${accountsservice_icon}
    SystemAccount=false
    | END

  # Account avatar shown by GDM and GNOME Shell
  file {
    default:
      owner => 'root',
      group => 'root',
    ;

    '/var/lib/AccountsService':
      ensure => directory,
      mode   => '0775',
    ;

    '/var/lib/AccountsService/icons':
      ensure => directory,
      mode   => '0775',
    ;

    '/var/lib/AccountsService/users':
      ensure => directory,
      mode   => '0700',
    ;

    $accountsservice_icon:
      mode    => '0644',
      source  => "/home/${nest::user}/.face.icon",
      require => Class['nest::base::users'],
    ;

    "/var/lib/AccountsService/users/${nest::user}":
      mode    => '0600',
      content => $accountsservice_user_content,
      require => File[$accountsservice_icon],
    ;
  }

  service { 'gdm':
    enable  => true,
    require => Nest::Lib::Package['gnome-base/gnome'],
  }
}
