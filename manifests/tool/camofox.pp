# Camofox Browser Nest tool image
#
# This installs the Jo Camofox Browser REST server and pre-fetches its Camoufox
# runtime during the image build so Kubernetes pods do not download browser
# binaries at startup.
class nest::tool::camofox (
  String $package_version          = '1.11.2',
  String $bitwarden_extension_url  = 'https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi',
  String $bitwarden_extension_path = '/opt/nest/camofox/extensions/bitwarden.xpi',
) {
  include 'nodejs'

  nest::lib::package { [
    'media-fonts/noto',
    'net-misc/curl',
    'x11-base/xorg-server',
  ]:
    ensure => installed,
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

  exec { 'install_camofox_bitwarden_extension':
    command => "/usr/bin/curl --fail --location --show-error --output ${bitwarden_extension_path} ${bitwarden_extension_url}",
    creates => $bitwarden_extension_path,
    require => [
      Nest::Lib::Package['net-misc/curl'],
      File['/opt/nest/camofox/extensions'],
    ],
    timeout => 0,
  }

  exec { 'install_camofox_browser':
    command     => "${nodejs::npm_path} install --global @askjo/camofox-browser@${package_version}",
    unless      => "${nodejs::npm_path} list --global @askjo/camofox-browser@${package_version} --depth=0 >/dev/null 2>&1",
    environment => ['HOME=/root'],
    require     => Class['nodejs'],
    timeout     => 0,
  }

  file { '/usr/local/bin/nest-camofox-browser':
    ensure  => file,
    mode    => '0755',
    content => [
      '#!/bin/sh',
      'set -eu',
      '',
      'export CAMOFOX_HOST="${CAMOFOX_HOST:-0.0.0.0}"',
      'export CAMOFOX_PORT="${CAMOFOX_PORT:-9377}"',
      'export CAMOFOX_DATA_DIR="${CAMOFOX_DATA_DIR:-/home/node/.camofox}"',
      'export HOME="${HOME:-/home/node}"',
      '',
      'mkdir -p "${CAMOFOX_DATA_DIR}" "${HOME}"',
      '',
      'exec camofox-browser "$@"',
      '',
    ].join("\n"),
    require => [
      Exec['install_camofox_browser'],
      Exec['install_camofox_bitwarden_extension'],
    ],
  }
}
