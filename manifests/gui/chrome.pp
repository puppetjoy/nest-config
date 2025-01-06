class nest::gui::chrome (
  String  $google_api_key,
  String  $google_oauth_id,
  String  $google_oauth_secret,
  Boolean $chromium = true,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      $gpu_compositing_flag = $facts['profile']['platform'] ? {
        /^(pinebookpro|raspberrypi4)$/ => 'disable-gpu-compositing',
        default                        => 'enable-gpu-compositing',
      }

      $gpu_rasterization_flag = $facts['virtual'] ? {
        'vmware' => 'disable-gpu-rasterization',
        default  => 'enable-gpu-rasterization',
      }

      if $chromium {
        unless $facts['build'] == 'stage1' {
          nest::lib::package { 'www-client/chromium':
            ensure => installed,
          }

          if $facts['profile']['architecture'] == 'amd64' {
            nest::lib::package { 'www-plugins/chrome-binary-plugins':
              ensure => installed,
            }
          }

          $chromium_flags = @("EOT"/$)
            [[ \$XDG_SESSION_TYPE == 'x11' ]] &&
                CHROMIUM_FLAGS="\${CHROMIUM_FLAGS} --force-device-scale-factor=${nest::text_scaling_factor} --enable-use-zoom-for-dsf"
            CHROMIUM_FLAGS="\${CHROMIUM_FLAGS} --${gpu_compositing_flag}"
            CHROMIUM_FLAGS="\${CHROMIUM_FLAGS} --${gpu_rasterization_flag}"
            CHROMIUM_FLAGS="\${CHROMIUM_FLAGS} --enable-oop-rasterization"
            CHROMIUM_FLAGS="\${CHROMIUM_FLAGS} --ignore-gpu-blocklist"

            # Workaround issue with dark Gtk theme detection and improve scrolling behavior
            # See: https://bugs.chromium.org/p/chromium/issues/detail?id=998903
            # See: https://wiki.archlinux.org/title/chromium#Dark_mode
            # See: https://bugs.chromium.org/p/chromium/issues/detail?id=1406625
            CHROMIUM_FLAGS="\${CHROMIUM_FLAGS} --force-dark-mode --enable-features=WebUIDarkMode,WindowsScrollingPersonality"

            # For Sync and other Google services
            # See: https://www.gentoo.org/support/news-items/2021-08-11-oauth2-creds-chromium.html
            export GOOGLE_API_KEY='${google_api_key}'
            export GOOGLE_DEFAULT_CLIENT_ID='${google_oauth_id}'
            export GOOGLE_DEFAULT_CLIENT_SECRET='${google_oauth_secret}'
            | EOT

          file { '/etc/chromium/nest':
            mode    => '0644',
            owner   => 'root',
            group   => 'root',
            content => $chromium_flags,
            require => Nest::Lib::Package['www-client/chromium'],
          }
        }

        nest::lib::package { 'www-client/google-chrome':
          ensure => absent,
        }
      } else {
        $chrome_wrapper = @("WRAPPER")
          #!/bin/bash
          exec /opt/google/chrome/google-chrome \
              --force-device-scale-factor=${nest::text_scaling_factor} \
              --${gpu_compositing_flag} \
              --${gpu_rasterization_flag} \
              --ignore-gpu-blocklist \
              --enable-features=WebUIDarkMode,WindowsScrollingPersonality \
              --force-dark-mode \
              --simulate-outdated-no-au='Tue, 31 Dec 2099 23:59:59 GMT' \
              "$@"
          | WRAPPER

        nest::lib::package { 'www-client/google-chrome':
          ensure => installed,
        }
        ->
        file { '/usr/bin/google-chrome-stable':
          mode    => '0755',
          owner   => 'root',
          group   => 'root',
          content => $chrome_wrapper,
        }

        nest::lib::package { [
          'www-client/chromium',
          'www-plugins/chrome-binary-plugins',
        ]:
          ensure => absent,
        }
        ->
        file { '/etc/chromium':
          ensure => absent,
          force  => true,
        }
      }

      # For casting
      unless $facts['build'] == 'stage1' { # firewalld not installed yet
        firewalld_service { 'mdns':
          ensure => present,
          zone   => 'home',
        }
      }
    }

    'windows': {
      package { 'googlechrome':
        ensure => installed,
      }
    }
  }
}
