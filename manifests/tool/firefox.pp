# Nest-owned Firefox/noVNC secure-browser tool image
#
# This image intentionally keeps Joy authority out of the image.  It provides a
# Portage Firefox runtime, Eyrie CA trust, Nest fonts, an in-container VNC
# framebuffer, and a web noVNC endpoint that matches the browser.eyrie service
# contract.  Persistent profile/session state remains a Kubernetes PVC mounted
# by the workload, not baked into the image.
class nest::tool::firefox (
  String $bitwarden_extension_id   = '{446900e4-71c2-419f-a6a7-df9c091e268b}',
  String $bitwarden_extension_url  = 'https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi',
  String $bitwarden_extension_path = '/opt/nest/firefox/extensions/bitwarden.xpi',
) {
  contain nest::gui::firefox
  contain nest::base::certs
  contain nest::gui::fonts

  # Firefox owns libnssckbi.so in the image; apply the p11-kit trust-store
  # replacement after the package so Firefox uses the Eyrie/Nest CA bundle.
  Class['nest::gui::firefox'] -> Class['nest::base::certs']

  nest::lib::package { [
    'dev-libs/openssl',
    'dev-python/websockify',
    'net-misc/curl',
    'www-apps/novnc',
    'x11-misc/xdotool',
    'x11-misc/x11vnc',
  ]:
    ensure => installed,
  }

  nest::lib::package { 'x11-base/xorg-server':
    ensure => installed,
    use    => 'xvfb',
  }

  file { '/opt/nest':
    ensure => directory,
    mode   => '0755',
  }

  file { '/opt/nest/firefox':
    ensure  => directory,
    mode    => '0755',
    require => File['/opt/nest'],
  }

  file { '/opt/nest/firefox/bin':
    ensure  => directory,
    mode    => '0755',
    require => File['/opt/nest/firefox'],
  }

  file { '/opt/nest/firefox/extensions':
    ensure  => directory,
    mode    => '0755',
    require => File['/opt/nest/firefox'],
  }

  file { '/opt/nest/firefox/bin/nest-firefox-browser.sh':
    ensure  => file,
    mode    => '0755',
    source  => 'puppet:///modules/nest/firefox-browser/nest-firefox-browser.sh',
    require => File['/opt/nest/firefox/bin'],
  }

  file { '/opt/nest/firefox/bin/smoke-firefox.sh':
    ensure  => file,
    mode    => '0755',
    source  => 'puppet:///modules/nest/firefox-browser/smoke-firefox.sh',
    require => File['/opt/nest/firefox/bin'],
  }

  file { '/opt/nest/firefox/novnc-index.html':
    ensure  => file,
    mode    => '0644',
    source  => 'puppet:///modules/nest/firefox-browser/novnc-index.html',
    require => File['/opt/nest/firefox'],
  }

  exec { 'install_firefox_bitwarden_extension':
    command => "/usr/bin/curl --fail --location --show-error --output ${bitwarden_extension_path} ${bitwarden_extension_url}",
    creates => $bitwarden_extension_path,
    require => [
      Nest::Lib::Package['net-misc/curl'],
      File['/opt/nest/firefox/extensions'],
    ],
    timeout => 0,
  }

  file { '/usr/lib64/firefox/distribution/extensions':
    ensure  => directory,
    mode    => '0755',
    require => Class['nest::gui::firefox'],
  }

  file { "/usr/lib64/firefox/distribution/extensions/${bitwarden_extension_id}.xpi":
    ensure  => link,
    target  => $bitwarden_extension_path,
    require => [
      Exec['install_firefox_bitwarden_extension'],
      File['/usr/lib64/firefox/distribution/extensions'],
    ],
  }

  # The browser.eyrie app consumes a Kasm-style HTTPS noVNC endpoint on 6901.
  # Gentoo does not package KasmVNC today, so the first Nest-owned image uses
  # package-managed noVNC + websockify + x11vnc as the observable web-VNC
  # equivalent while keeping Firefox itself Portage-managed.
  file { '/opt/noVNC':
    ensure  => link,
    target  => '/usr/share/novnc',
    require => Nest::Lib::Package['www-apps/novnc'],
  }

  file { '/usr/share/novnc/index.html':
    ensure  => link,
    target  => '/opt/nest/firefox/novnc-index.html',
    require => [
      File['/opt/nest/firefox/novnc-index.html'],
      Nest::Lib::Package['www-apps/novnc'],
    ],
  }

  file { '/usr/local/bin/nest-firefox-browser':
    ensure  => link,
    target  => '/opt/nest/firefox/bin/nest-firefox-browser.sh',
    require => File['/opt/nest/firefox/bin/nest-firefox-browser.sh'],
  }
}
