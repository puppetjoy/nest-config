class nest::gui::gnome {
  contain nest::gui::keyboard

  # Mutter has an unexpressed dependency on rst2man
  nest::lib::package { 'dev-python/docutils':
    ensure => installed,
  }
  ->
  nest::lib::package { 'gnome-base/gnome':
    ensure => installed,
    before => Class['nest::base::dconf'],
  }

  $keyboard_source = $nest::dvorak ? {
    true    => 'us+dvorak',
    default => 'us',
  }

  $xkb_options = $nest::swap_alt_win ? {
    true    => "['ctrl:nocaps', 'altwin:swap_alt_win']",
    default => "['ctrl:nocaps']",
  }

  nest::lib::dconf { 'keyboard':
    settings => {
      'org/gnome/desktop/input-sources' => {
        'sources'     => "[('xkb', '${keyboard_source}')]",
        'xkb-options' => $xkb_options,
      },
    },
    locks    => true,
  }

  nest::lib::dconf { 'console':
    settings => {
      'org/gnome/Console' => {
        'custom-font'              => "'Adwaita Mono 10'",
        'use-system-font'          => 'false',
      },
    },
  }

  nest::lib::dconf { 'session':
    settings => {
      'org/gnome/desktop/screensaver'           => {
        'idle-activation-enabled' => 'false',
        'lock-enabled'            => 'false',
      },
      'org/gnome/desktop/session'               => {
        'idle-delay'                  => 'uint32 0',
      },
      'org/gnome/settings-daemon/plugins/power' => {
        'sleep-inactive-battery-type' => "'nothing'",
      },
    },
  }

  if $nest::idle_brightness != undef {
    nest::lib::dconf { 'idle-brightness':
      settings => {
        'org/gnome/settings-daemon/plugins/power' => {
          'idle-brightness' => String($nest::idle_brightness),
        },
      },
      locks    => true,
    }
  }

  if $nest::autologin == true {
    $gdm_autologin_enable = 'True'
    $gdm_autologin_ensure = 'present'
  } else {
    $gdm_autologin_enable = 'False'
    $gdm_autologin_ensure = 'absent'
  }

  ini_setting {
    default:
      path    => '/etc/gdm/custom.conf',
      section => 'daemon',
      require => Nest::Lib::Package['gnome-base/gnome'],
    ;

    'gdm-custom.conf-AutomaticLoginEnable':
      setting => 'AutomaticLoginEnable',
      value   => $gdm_autologin_enable,
    ;

    'gdm-custom.conf-AutomaticLogin':
      ensure  => $gdm_autologin_ensure,
      setting => 'AutomaticLogin',
      value   => $nest::user,
    ;
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
