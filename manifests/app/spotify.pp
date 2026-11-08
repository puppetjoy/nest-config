# Explicit host opt-in; personal workspace and media-key policy lives in dotfiles.
class nest::app::spotify (
  Enum['native', 'web'] $backend               = 'native',
  Boolean               $hardware_video_decode = true,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      if $backend == 'web' {
        # Keep the vendor-supported ARM64 browser package, not a transplanted CDM.
        nest::lib::package { 'www-client/google-chrome':
          ensure => installed,
        }

        # X11 desktop tooling is already owned by nest::gui::xorg.
        $launcher_require = [
          Nest::Lib::Package['www-client/google-chrome'],
          Nest::Lib::Package['x11-misc/xdotool'],
        ]
      } else {
        if $facts['profile']['architecture'] != 'amd64' {
          fail('Native Spotify on Gentoo requires amd64; select the web backend on ARM64')
        }

        # Spotify's Ayatana indicator requires the GTK 3 libdbusmenu ABI.
        nest::lib::package_use { 'spotify-libdbusmenu':
          package => 'dev-libs/libdbusmenu',
          use     => ['gtk3'],
        }
        ->
        nest::lib::package { 'media-sound/spotify':
          ensure => installed,
        }

        $launcher_require = Nest::Lib::Package['media-sound/spotify']
      }

      file { '/usr/local/bin/nest-spotify':
        owner   => 'root',
        group   => 'root',
        mode    => '0755',
        content => template('nest/spotify/launcher.erb'),
        require => $launcher_require,
      }

      if $backend == 'web' {
        # An app-mode shortcut, not a claim that a PWA has been installed.
        file { '/usr/share/applications/nest-spotify.desktop':
          owner   => 'root',
          group   => 'root',
          mode    => '0644',
          content => @(DESKTOP),
            [Desktop Entry]
            Type=Application
            Name=Spotify
            Comment=Spotify web player in a dedicated Chrome profile
            Exec=/usr/local/bin/nest-spotify
            Icon=audio-x-generic
            Terminal=false
            Categories=Audio;Music;Player;
            StartupWMClass=nest-spotify
            | DESKTOP
          require => File['/usr/local/bin/nest-spotify'],
        }
      }
    }

    'Darwin': {
      if $backend != 'native' {
        fail('Spotify on macOS uses the official native client')
      }

      package { 'spotify':
        ensure => installed,
      }
    }

    default: {
      fail('Managed Spotify supports Gentoo and macOS')
    }
  }
}
