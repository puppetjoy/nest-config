class nest::gui::firefox {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { 'www-client/firefox':
        ensure => installed,
        use    => 'hwaccel',
      }

      $webrender = $facts['profile']['platform'] ? {
        'raspberrypi4' => 0,
        default        => 1,
      }

      $autoconfig_content = @(AUTOCONFIG)
        pref("general.config.filename", "firefox.cfg");
        pref("general.config.obscure_value", 0);
        | AUTOCONFIG

      file {
        default:
          owner   => 'root',
          group   => 'root',
          require => Nest::Lib::Package['www-client/firefox'],
        ;

        '/usr/local/bin/firefox':
          mode    => '0755',
          content => template('nest/firefox/wrapper.erb'),
        ;

        '/usr/local/bin/firefox-wayland':
          mode   => '0755',
          source => 'puppet:///modules/nest/firefox/firefox-wayland',
        ;

        '/usr/local/bin/firefox-x11':
          mode   => '0755',
          source => 'puppet:///modules/nest/firefox/firefox-x11',
        ;

        '/usr/lib64/firefox/firefox.cfg':
          mode    => '0644',
          content => template('nest/firefox/firefox.cfg.erb'),
        ;

        '/usr/lib64/firefox/defaults/pref/autoconfig.js':
          mode    => '0644',
          content => $autoconfig_content,
        ;

        '/usr/lib64/firefox/defaults/pref/all-nest.js':
          ensure => absent,
        ;

        # Load CA certs from system store
        # Also works for Chromium
        # See: https://superuser.com/a/1836165
        '/usr/lib64/libnssckbi.so':
          ensure => link,
          target => '/usr/lib64/pkcs11/p11-kit-trust.so',
        ;
      }
    }

    'windows': {
      package { 'firefox':
        ensure => installed,
      }

      file {
        default:
          owner => $nest::user,
        ;

        "C:/Users/${nest::user}/AppData/Roaming/Mozilla":
          ensure => directory,
        ;

        "C:/Users/${nest::user}/AppData/Roaming/Mozilla/Firefox":
          ensure => link,
          target => "C:/tools/cygwin/home/${nest::user}/.mozilla/firefox",
        ;
      }
    }
  }
}
