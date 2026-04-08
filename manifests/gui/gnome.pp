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

  nest::lib::package { 'gnome-extra/gnome-browser-connector':
    ensure => installed,
  }

  if $nest::kernel_config['CONFIG_HID_SENSOR_HUB'] in ['Y', 'y', 'm'] {
    nest::lib::package { 'gnome-extra/iio-sensor-proxy':
      ensure => installed,
    }
  }

  # Hide launchers that GNOME would otherwise surface prominently while
  # leaving their underlying desktop entry metadata available in overlay
  # copies under /usr/local/share/applications.
  $hidden_desktop_entries = [
    'Gentoo-system-config-printer.desktop',
    'amdgpu_top-tui.desktop',
    'amdgpu_top.desktop',
    'assistant.desktop',
    'bssh.desktop',
    'bvnc.desktop',
    'ca.desrt.dconf-editor.desktop',
    'cups.desktop',
    'distccmon-gnome.desktop',
    'firewall-config.desktop',
    'gnome-system-monitor-kde.desktop',
    'htop.desktop',
    'linguist.desktop',
    'mpv.desktop',
    'mupdf.desktop',
    'nm-connection-editor.desktop',
    'nvidia-settings.desktop',
    'nvtop.desktop',
    'org.freedesktop.IBus.Setup.desktop',
    'org.gnome.ColorProfileViewer.desktop',
    'org.gnome.Connections.desktop',
    'org.gnome.Console.desktop',
    'org.gnome.Contacts.desktop',
    'org.gnome.Evince.desktop',
    'org.gnome.Evolution.desktop',
    'org.gnome.Sysprof.desktop',
    'org.gnome.Vte.App.Gtk4.desktop',
    'org.gnome.font-viewer.desktop',
    'org.gnome.seahorse.Application.desktop',
    'qdbusviewer.desktop',
    'qv4l2.desktop',
    'qvidcap.desktop',
    'vim.desktop',
    'yelp.desktop',
  ]

  file {
    '/usr/local/bin/nest-gnome-desktop-overlays':
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => epp('nest/scripts/gnome-desktop-overlays.sh.epp', { 'desktop_entries' => $hidden_desktop_entries }),
    ;

    '/usr/local/share/applications':
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    ;
  }
  ->
  exec { 'sync-gnome-desktop-overlays':
    command => '/usr/local/bin/nest-gnome-desktop-overlays --apply',
    unless  => '/usr/local/bin/nest-gnome-desktop-overlays --check',
  }

  Package <||> -> Exec['sync-gnome-desktop-overlays']

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

  if $nest::ambient_enabled != undef {
    nest::lib::dconf { 'ambient-enabled':
      settings => {
        'org/gnome/settings-daemon/plugins/power' => {
          'ambient-enabled' => String($nest::ambient_enabled),
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
