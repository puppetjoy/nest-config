# Camofox Browser Nest tool image
#
# This installs the Jo Camofox Browser REST server and pre-fetches its Camoufox
# runtime during the image build so Kubernetes pods do not download browser
# binaries at startup.
class nest::tool::camofox (
  String $package_version = '1.11.2',
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
    require => Exec['install_camofox_browser'],
  }
}
