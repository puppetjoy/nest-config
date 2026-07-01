# Camofox Browser Nest tool image
#
# This installs the Jo Camofox Browser REST server and pre-fetches its Camoufox
# runtime during the image build so Kubernetes pods do not download browser
# binaries at startup.
class nest::tool::camofox (
  String $package_name             = 'camofox-browser',
  String $package_version          = '2.4.6',
  String $bitwarden_extension_url  = 'https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi',
  String $bitwarden_extension_path = '/opt/nest/camofox/extensions/bitwarden.xpi',
) {
  include 'nodejs'

  nest::lib::package { [
    'dev-python/websockify',
    'media-fonts/noto',
    'media-libs/alsa-lib',
    'net-misc/curl',
    'www-apps/novnc',
    'x11-libs/gtk+',
    'x11-misc/x11vnc',
  ]:
    ensure => installed,
    before => Exec['install_camofox_browser'],
  }

  nest::lib::package { 'x11-base/xorg-server':
    ensure => installed,
    use    => 'xvfb',
    before => Exec['install_camofox_browser'],
  }

  file { '/opt/nest':
    ensure => directory,
    mode   => '0755',
  }

  file { '/opt/nest/camofox':
    ensure  => directory,
    mode    => '0755',
    require => File['/opt/nest'],
  }

  file { '/opt/nest/camofox/extensions':
    ensure  => directory,
    mode    => '0755',
    require => File['/opt/nest/camofox'],
  }

  file { '/opt/nest/camofox/bin':
    ensure  => directory,
    mode    => '0755',
    require => File['/opt/nest/camofox'],
  }

  file { '/opt/nest/camofox/bin/smoke-tabs.sh':
    ensure  => file,
    mode    => '0755',
    source  => 'puppet:///modules/nest/camofox-browser/smoke-tabs.sh',
    require => File['/opt/nest/camofox/bin'],
  }

  file { '/opt/nest/camofox/bin/nest-camofox-browser.sh':
    ensure  => file,
    mode    => '0755',
    source  => 'puppet:///modules/nest/camofox-browser/nest-camofox-browser.sh',
    require => File['/opt/nest/camofox/bin'],
  }

  # Camofox Browser's VNC helper expects the noVNC web root at /opt/noVNC.
  # Gentoo installs the package-managed assets under /usr/share/novnc.
  file { '/opt/noVNC':
    ensure  => link,
    target  => '/usr/share/novnc',
    require => Nest::Lib::Package['www-apps/novnc'],
  }

  exec { 'install_camofox_bitwarden_extension':
    command => "/usr/bin/curl --fail --location --show-error --output ${bitwarden_extension_path} ${bitwarden_extension_url}",
    creates => $bitwarden_extension_path,
    require => [
      Nest::Lib::Package['net-misc/curl'],
      File['/opt/nest/camofox/extensions'],
    ],
    timeout => 0,
  }

  exec { 'remove_legacy_askjo_camofox_browser':
    command     => "${nodejs::npm_path} uninstall --global @askjo/camofox-browser",
    onlyif      => "${nodejs::npm_path} list --global @askjo/camofox-browser --depth=0 >/dev/null 2>&1",
    environment => ['HOME=/root'],
    require     => Class['nodejs'],
    before      => Exec['install_camofox_browser'],
    timeout     => 0,
  }

  exec { 'install_camofox_browser':
    command     => "${nodejs::npm_path} install --global ${package_name}@${package_version}",
    unless      => "${nodejs::npm_path} list --global ${package_name}@${package_version} --depth=0 >/dev/null 2>&1",
    environment => ['HOME=/root'],
    require     => Class['nodejs'],
    timeout     => 0,
  }

  file { '/usr/local/bin/nest-camofox-browser':
    ensure  => link,
    target  => '/opt/nest/camofox/bin/nest-camofox-browser.sh',
    require => [
      Exec['install_camofox_browser'],
      Exec['install_camofox_bitwarden_extension'],
      File['/opt/nest/camofox/bin/nest-camofox-browser.sh'],
    ],
  }
}
