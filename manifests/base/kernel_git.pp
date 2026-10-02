# Project-scoped read access for builds and manual root fetches on hosts.
# Credential embedding in Stage2/Stage3 images is intentional.
class nest::base::kernel_git {
  if $nest::linux_git_credential {
    file { '/etc/nest-linux-git-credential':
      ensure    => file,
      owner     => 'root',
      group     => 'root',
      mode      => '0600',
      content   => $nest::linux_git_credential,
      show_diff => false,
      tag       => 'linux_git_auth',
    }

    file { '/usr/local/sbin/nest-linux-git-credential':
      ensure => file,
      owner  => 'root',
      group  => 'root',
      mode   => '0755',
      source => 'puppet:///modules/nest/scripts/linux-git-credential.sh',
      tag    => 'linux_git_auth',
    }

    ini_setting { 'linux-git-credential-helper':
      path    => '/etc/gitconfig',
      section => 'credential "https://gitlab.joyfullee.me/nest/forks/linux.git"',
      setting => 'helper',
      value   => '/usr/local/sbin/nest-linux-git-credential',
      require => File['/usr/local/sbin/nest-linux-git-credential', '/etc/nest-linux-git-credential'],
      tag     => 'linux_git_auth',
    }

    ini_setting { 'linux-git-credential-path':
      path    => '/etc/gitconfig',
      section => 'credential "https://gitlab.joyfullee.me/nest/forks/linux.git"',
      setting => 'useHttpPath',
      value   => 'true',
      tag     => 'linux_git_auth',
    }
  }
}
