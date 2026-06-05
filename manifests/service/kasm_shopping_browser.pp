class nest::service::kasm_shopping_browser (
  Sensitive[String]                $vnc_password,
  Stdlib::Port                     $port              = 6901,
  String                           $image             = 'docker.io/kasmweb/chrome:1.18.0',
  Stdlib::Absolutepath             $profile_root      = '/srv/kasm/shopping',
  Stdlib::Absolutepath             $policy_root       = '/srv/kasm/shopping/policies',
  String                           $bitwarden_id      = 'nngceckbapebfimnlniiiahkandclblb',
  String                           $extension_updates = 'https://clients2.google.com/service/update2/crx',
  Array[Stdlib::Host]              $launch_urls       = ['https://www.amazon.com/', 'https://bitwarden.eyrie/'],
  Array[Enum['home', 'internal']]  $firewall_zones    = ['home', 'internal'],
) {
  unless $facts['is_container'] {
    require 'nest::base::containers'

    $profile_dir = "${profile_root}/profile"

    nest::lib::srv { 'kasm': }

    file { [
        $profile_root,
        $profile_dir,
        $policy_root,
        "${policy_root}/chrome",
        "${policy_root}/chromium",
      ]:
      ensure => directory,
      owner  => '1000',
      group  => '1000',
      mode   => '0700',
    }

    file { "${policy_root}/bitwarden-extension.json":
      ensure  => file,
      owner   => 'root',
      group   => 'root',
      mode    => '0644',
      content => stdlib::to_json({
        ExtensionInstallForcelist => ["${bitwarden_id};${extension_updates}"],
        ExtensionSettings         => {
          $bitwarden_id => {
            installation_mode => 'force_installed',
            update_url        => $extension_updates,
            toolbar_pin       => 'force_pinned',
          },
        },
      }),
    }

    file { "${policy_root}/chrome/bitwarden-extension.json":
      ensure => link,
      target => "${policy_root}/bitwarden-extension.json",
    }

    file { "${policy_root}/chromium/bitwarden-extension.json":
      ensure => link,
      target => "${policy_root}/bitwarden-extension.json",
    }

    nest::lib::secret { 'kasm-shopping-vnc-password':
      value => $vnc_password,
    }

    nest::lib::container { 'kasm-shopping-browser':
      image    => $image,
      publish  => ["${port}:6901"],
      shm_size => '512m',
      env      => [
        "LAUNCH_URL=${launch_urls.join(',')}",
        'KASM_RESTRICTED_FILE_CHOOSER=1',
      ],
      secrets  => {
        'kasm-shopping-vnc-password' => 'VNC_PW',
      },
      volumes  => [
        "${profile_dir}:/home/kasm-user",
        "${policy_root}/chrome:/etc/opt/chrome/policies/managed:ro",
        "${policy_root}/chromium:/etc/chromium/policies/managed:ro",
      ],
      require  => [
        File[$profile_dir],
        File["${policy_root}/chrome/bitwarden-extension.json"],
        File["${policy_root}/chromium/bitwarden-extension.json"],
        Nest::Lib::Secret['kasm-shopping-vnc-password'],
      ],
    }

    $firewall_zones.each |$zone| {
      firewalld_port { "kasm-shopping-browser-${zone}":
        ensure   => present,
        zone     => $zone,
        port     => $port,
        protocol => 'tcp',
      }
    }

    file { '/usr/local/sbin/reset-kasm-shopping-browser':
      ensure  => file,
      owner   => 'root',
      group   => 'root',
      mode    => '0755',
      content => @(SCRIPT),
        #!/bin/sh
        set -eu

        systemctl stop container-kasm-shopping-browser.service 2>/dev/null || true
        podman container rm kasm-shopping-browser 2>/dev/null || true
        rm -rf ${profile_dir}
        install -d -o 1000 -g 1000 -m 0700 ${profile_dir}

        cat <<'EOF'
        Kasm shopping browser stopped and profile state wiped.

        To rotate the KasmVNC UI password, update
        nest::service::kasm_shopping_browser::vnc_password in private Hiera,
        run Puppet on this host, and then start container-kasm-shopping-browser.
        EOF
        | SCRIPT
    }
  }
}
