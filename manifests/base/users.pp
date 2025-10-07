class nest::base::users {
  case $facts['os']['family'] {
    'Gentoo': {
      file { '/bin/zsh':
        ensure => file,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }

      nest::lib::package { 'app-shells/zsh':
        ensure => installed,
      }

      group {
        $nest::user:
          gid => '1000';
        'media':
          gid => '1001',
        ;
      }

      # Useradd wants to create home directories by default.  We can explicitly
      # control this behavior with the 'managehome' attribute.
      file_line { 'login.defs-create_home':
        path  => '/etc/login.defs',
        line  => 'CREATE_HOME no',
        match => '^CREATE_HOME ',
      }

      user {
        default:
          managehome => false,
          require    => File_line['login.defs-create_home'],
        ;

        'root':
          shell    => '/bin/zsh',
          require  => File['/bin/zsh'],
          password => $nest::pw_hash,
        ;

        $nest::user:
          uid      => '1000',
          gid      => $nest::user,
          groups   => ['wheel'],
          home     => "/home/${nest::user}",
          comment  => $nest::user_fullname,
          shell    => '/bin/zsh',
          password => $nest::pw_hash,
          require  => Nest::Lib::Package['app-shells/zsh'],
        ;

        'media':
          uid     => '1001',
          gid     => 'media',
          home    => '/dev/null',
          comment => 'Media Services',
          shell   => '/sbin/nologin',
        ;
      }

      # Early stages often have hidden files blocking vcsrepo initialization
      exec { '/bin/rm -rf /root':
        unless => '/usr/bin/test -d /root/.git',
        before => File['/root'],
      }

      file {
        '/root':
          ensure => directory,
          mode   => '0700',
          owner  => 'root',
          group  => 'root',
          before => Vcsrepo['/root'],
        ;

        "/home/${nest::user}":
          ensure => directory,
          mode   => '0755',
          owner  => $nest::user,
          group  => $nest::user,
          before => Vcsrepo["/home/${nest::user}"],
        ;
      }

      $homes = {
        'root'      => '/root',
        $nest::user => "/home/${nest::user}",
      }
    }

    'windows': {
      package { 'zsh':
        ensure   => installed,
        provider => 'cygwin',
      }

      windows_env { "${nest::user}-SHELL":
        user     => $nest::user,
        variable => 'SHELL',
        value    => '/bin/zsh',
        require  => Package['zsh'],
      }

      $homes = {
        $nest::user => "/home/${nest::user}",
      }
    }
  }

  $homes.each |$user, $dir| {
    case $facts['os']['family'] {
      'windows': {
        $exec_user   = undef
        $home_dir    = "C:/tools/cygwin${dir}"
        $refresh_cmd = "C:/tools/cygwin/bin/bash.exe -c 'source /etc/profile && ${home_dir}/.refresh'"
        $test_cmd    = "C:/tools/cygwin/bin/test.exe -x ${home_dir}/.refresh"
      }

      default: {
        $exec_user   = $user
        $home_dir    = $dir
        $refresh_cmd = "${home_dir}/.refresh"
        $test_cmd    = "/usr/bin/test -x ${home_dir}/.refresh"
      }
    }

    vcsrepo { $home_dir:
      ensure   => latest,
      provider => git,
      source   => "https://gitlab.james.tl/${nest::user}/dotfiles.git",
      revision => 'main',
      user     => $exec_user,
    }
    ~>
    exec { "refresh-${home_dir}":
      environment => "HOME=${home_dir}",
      command     => $refresh_cmd,
      user        => $exec_user,
      onlyif      => $test_cmd,
      refreshonly => true,
      subscribe   => Class['nest::base::puppet'],
    }

    if $nest::ssh_private_keys[$user] {
      file { "${home_dir}/.ssh/id_ed25519":
        mode      => '0600',
        owner     => $user,
        content   => $nest::ssh_private_keys[$user],
        show_diff => false,
        require   => Vcsrepo[$home_dir],
      }
    } else {
      file { "${home_dir}/.ssh/id_ed25519":
        ensure => absent,
      }
    }
  }
}
