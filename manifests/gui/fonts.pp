class nest::gui::fonts {
  case $facts['os']['family'] {
    'Gentoo': {
      $fontconfig_local_conf = '/etc/fonts/local.conf'

      File {
        owner => 'root',
        group => 'root',
        mode  => '0644',
      }

      nest::lib::package { 'media-fonts/corefonts':
        ensure => installed,
        use    => 'tahoma',
      }
      # fontconfig is pulled in by the portage profile, and all packages
      # depend on the portage profile, so this is just an easy way to
      # establish that relationship.
      -> File[$fontconfig_local_conf]

      nest::lib::package { [
        'media-fonts/fontawesome',
        'media-fonts/hack',
        'media-fonts/liberation-fonts', # primarily for GitHub, tbh
        'media-fonts/noto-emoji',
      ]:
        ensure => installed,
      }
    }

    'Darwin': {
      $fontconfig_local_conf = undef

      package { 'font-powerline-symbols':
        ensure => installed,
      }
    }

    'windows': {
      require 'nest::gui::xorg'

      $fontconfig_local_conf = 'C:/tools/cygwin/etc/fonts/local.conf'

      File {
        owner => 'Administrators',
        group => 'None',
        mode  => '0644',
      }

      file { 'C:/tools/cygwin/usr/share/fonts/hack':
        ensure  => directory,
        source  => 'puppet:///modules/nest/fonts/hack',
        recurse => true,
      }
    }
  }

  # The intention here is to express configurations that are related to the
  # system, not necessarily my preference. User preference type
  # configurations, like hinting, belong in the user's home directory
  # (~/.config/fontconfig/fonts.conf)
  if $fontconfig_local_conf {
    file { $fontconfig_local_conf:
      content => epp('nest/fonts/local.conf.epp', {
        subpixel_rendering => $nest::subpixel_rendering,
      }),
    }
  }
}
