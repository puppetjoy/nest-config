define nest::lib::toolchain (
  Enum['present', 'absent'] $ensure   = present,
  Hash                      $env      = {},
  Optional[String]          $gcc_conf = undef,
  Boolean                   $gcc_only = false,
) {
  case $ensure {
    'present': {
      include 'nest::lib::crossdev'

      if $gcc_conf {
        $env_real = $env + { 'EXTRA_ECONF' => $gcc_conf }
      } else {
        $env_real = $env
      }

      $env_args = $env_real.map |$k,$v| { "${k}=${v.shellquote}" }.join(' ')

      if $env_args.empty {
        $gcc_conf_args = ''
      } else {
        $gcc_conf_args = "--genv ${env_args.shellquote}"
      }

      if $gcc_only {
        $stage_arg = '--stage1'
        $installed_check = "/usr/bin/${name}-gcc --version"
      } else {
        $stage_arg = ''
        $installed_check = "/usr/bin/${name}-gcc --version && /usr/bin/${name}-g++ --version"
      }

      exec { "crossdev-install-${name}":
        command => "/usr/bin/crossdev ${gcc_conf_args} --stable --portage '--usepkg' ${stage_arg} --target ${name}",
        unless  => $installed_check,
        timeout => 0,
        require => Class['nest::lib::crossdev'],
      }
      ->
      file {
        "/etc/portage/env/cross-${name}":
          ensure => directory,
        ;

        [
          "/etc/portage/package.accept_keywords/cross-${name}",
          "/etc/portage/package.env/cross-${name}",
          "/etc/portage/package.use/cross-${name}",
          "/etc/portage/profile/package.use.force/cross-${name}",
          "/etc/portage/profile/package.use.mask/cross-${name}",
        ]:
          ensure => file,
        ;
      }

      if $nest::distcc_server {
        Exec["crossdev-install-${name}"] ~> Exec['update-distcc-compiler-links']
      }

      if $facts['llvm_clang'] {
        file {
          default:
            ensure => link,
            notify => Class['nest::base::distccd'];
          "/usr/local/bin/${name}-clang":
            target => $facts['llvm_clang'];
          "/usr/local/bin/${name}-clang++":
            target => "${facts['llvm_clang']}++",
          ;
        }

        if $facts['llvm_clang'] =~ /\/(\d+)\// {
          $llvm_version = $1
          file {
            default:
              ensure => link,
              notify => Class['nest::base::distccd'];
            "/usr/local/bin/${name}-clang-${llvm_version}":
              target => $facts['llvm_clang'];
            "/usr/local/bin/${name}-clang++-${llvm_version}":
              target => "${facts['llvm_clang']}++",
            ;
          }
        }
      }
    }

    'absent': {
      exec { "crossdev-uninstall-${name}":
        command => "/usr/bin/crossdev -C ${name}",
        onlyif  => "/usr/bin/test -e /usr/bin/${name}-gcc",
      }

      if defined(Tidy['/usr/local/bin']) {
        Tidy <| title == '/usr/local/bin' |> {
          matches +> ["${name}-clang*", "${name}-clang++*"],
        }
      } else {
        tidy { '/usr/local/bin':
          matches => ["${name}-clang*", "${name}-clang++*"],
          recurse => 1,
        }
      }
    }
  }
}
