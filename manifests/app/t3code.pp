class nest::app::t3code {
  include 'nest'

  case $facts['os']['family'] {
    'Gentoo': {
      include 'nest::app::codex'

      $home        = "/home/${nest::user}"
      $install_dir = "${home}/Applications/t3code"
      $appimage    = "${install_dir}/t3code.AppImage"
      $icon        = "${install_dir}/t3code.png"
      $desktop_dir = "${home}/.local/share/applications"
      $desktop_file = "${desktop_dir}/t3code.desktop"

      nest::lib::package { 'fuse2':
        ensure  => installed,
        package => 'sys-fs/fuse:0',
      }

      file {
        default:
          ensure  => directory,
          mode    => '0755',
          owner   => $nest::user,
          group   => $nest::user,
          require => Class['nest::base::users'],
        ;

        "${home}/Applications":
          before => File[$install_dir],
        ;

        $install_dir:
          before => Exec['install-t3code'],
        ;

        "${home}/.local":
          before => File["${home}/.local/share"],
        ;

        "${home}/.local/share":
          before => File[$desktop_dir],
        ;

        $desktop_dir:
          before => File[$desktop_file],
        ;
      }

      file { '/usr/local/bin/nest-t3code-update':
        ensure  => file,
        mode    => '0755',
        owner   => 'root',
        group   => 'root',
        content => epp('nest/scripts/t3code-update.sh.epp', {
          'appimage'    => $appimage,
          'icon'        => $icon,
          'install_dir' => $install_dir,
        }),
      }

      exec { 'install-t3code':
        command     => '/usr/local/bin/nest-t3code-update',
        unless      => '/usr/local/bin/nest-t3code-update --check',
        environment => ["HOME=${home}"],
        user        => $nest::user,
        require     => [
          Class['nest::app::codex'],
          File['/usr/local/bin/nest-t3code-update'],
          File[$install_dir],
          Nest::Lib::Package['fuse2'],
        ],
      }

      file { $desktop_file:
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => epp('nest/t3code/t3code.desktop.epp', {
          'appimage' => $appimage,
          'icon'     => $icon,
        }),
        require => Exec['install-t3code'],
      }
    }
  }
}
