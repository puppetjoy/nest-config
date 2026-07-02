# Nest-owned Firefox/KasmVNC secure-browser tool image
#
# This image intentionally keeps Joy authority out of the image. It provides a
# workstation-derived Portage Firefox/xmonad runtime, source-built KasmVNC, Eyrie
# CA trust, Nest fonts, and the web-VNC endpoint that matches the browser.eyrie
# service contract.
# Persistent profile/session state remains a Kubernetes PVC mounted by the
# workload, not baked into the image.
class nest::tool::firefox (
  String $bitwarden_extension_id   = '{446900e4-71c2-419f-a6a7-df9c091e268b}',
  String $bitwarden_extension_url  = 'https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi',
  String $bitwarden_extension_path = '/opt/nest/firefox/extensions/bitwarden.xpi',
  String $kasmvnc_revision         = 'v1.4.0',
  String $kasmvnc_xorg_version     = '1.20.14',
) {
  contain nest::base::certs
  include nodejs

  # The Firefox tool image is built from nest/stage1/workstation:haswell, which
  # already carries Portage Firefox, xmonad, and the Nest font collection. Keep
  # this class focused on browser.eyrie-specific KasmVNC glue, CA trust refresh,
  # Bitwarden extension policy material, and the minimal fullscreen xmonad
  # application config.

  nest::lib::package { [
    'dev-build/autoconf',
    'dev-build/automake',
    'dev-build/cmake',
    'dev-build/libtool',
    'dev-build/ninja',
    'dev-cpp/tbb',
    'dev-libs/openssl',
    'dev-lang/nasm',
    'dev-util/sccache',
    'dev-vcs/git',
    'media-libs/flac',
    'media-libs/freetype',
    'media-libs/libjpeg-turbo',
    'media-libs/libpng',
    'media-libs/libva',
    'media-fonts/font-util',
    'media-video/ffmpeg',
    'net-misc/curl',
    'net-misc/wget',
    'sys-libs/pam',
    'x11-apps/xauth',
    'x11-apps/xkbcomp',
    'x11-libs/libICE',
    'x11-libs/libSM',
    'x11-libs/libX11',
    'x11-libs/libXau',
    'x11-libs/libXdmcp',
    'x11-libs/libXext',
    'x11-libs/libXfont2',
    'x11-libs/libXrender',
    'x11-libs/libXtst',
    'x11-libs/libdrm',
    'net-libs/libtirpc',
    'x11-libs/libxkbfile',
    'x11-libs/pixman',
    'x11-misc/util-macros',
    'x11-misc/xdotool',
    'x11-misc/xkeyboard-config',
  ]:
    ensure => installed,
    before => [
      Nest::Lib::Build['kasmvnc'],
      Exec['install_firefox_bitwarden_extension'],
    ],
  }

  nest::lib::src_repo { '/usr/src/KasmVNC':
    url => 'https://github.com/kasmtech/KasmVNC.git',
    ref => $kasmvnc_revision,
  }
  ~>
  nest::lib::build { 'kasmvnc':
    dir     => '/usr/src/KasmVNC',
    distcc  => false,
    command => [
      "KASMVNC_MAKE_JOBS=\"${facts['processors']['count']}\" NPM_COMMAND=\"${nodejs::npm_path}\" XORG_VER=\"${kasmvnc_xorg_version}\" /opt/nest/firefox/bin/build-kasmvnc.sh /usr/src/KasmVNC",
    ],
    require => [
      Class['nodejs'],
      File['/opt/nest/firefox/bin/build-kasmvnc.sh'],
    ],
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

  file { '/opt/nest/firefox/bin/build-kasmvnc.sh':
    ensure  => file,
    mode    => '0755',
    source  => 'puppet:///modules/nest/firefox-browser/build-kasmvnc.sh',
    require => File['/opt/nest/firefox/bin'],
    notify  => Exec['kasmvnc-build'],
  }

  file { '/opt/nest/firefox/bin/smoke-firefox.sh':
    ensure  => file,
    mode    => '0755',
    source  => 'puppet:///modules/nest/firefox-browser/smoke-firefox.sh',
    require => File['/opt/nest/firefox/bin'],
  }

  file { '/opt/nest/firefox/xmonad.hs':
    ensure  => file,
    mode    => '0644',
    source  => 'puppet:///modules/nest/firefox-browser/xmonad.hs',
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
    ensure => directory,
    mode   => '0755',
  }

  file { "/usr/lib64/firefox/distribution/extensions/${bitwarden_extension_id}.xpi":
    ensure  => link,
    target  => $bitwarden_extension_path,
    require => [
      Exec['install_firefox_bitwarden_extension'],
      File['/usr/lib64/firefox/distribution/extensions'],
    ],
  }

  file { '/usr/local/bin/nest-firefox-browser':
    ensure  => link,
    target  => '/opt/nest/firefox/bin/nest-firefox-browser.sh',
    require => [
      File['/opt/nest/firefox/bin/nest-firefox-browser.sh'],
      Nest::Lib::Build['kasmvnc'],
    ],
  }
}
