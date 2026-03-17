class nest::base::sudo {
  case $facts['os']['family'] {
    'Gentoo': {
      $config_group    = 'root'
      $config_dir_mode = '0750'
      $sudoer_id       = '%wheel'

      nest::lib::package { 'app-admin/sudo':
        ensure  => installed,
        require => Class['nest::base::mta'],
        before  => File['/etc/sudoers.d'],
      }
    }

    'Darwin': {
      $config_group    = 'wheel'
      $config_dir_mode = '0755'
      $sudoer_id       = $nest::user
    }
  }

  $sudoer_content = @("SUDO")
    Defaults env_keep -= "HOME"
    Defaults env_keep += "KUBECONFIG SSH_AUTH_SOCK SSH_CLIENT SSH_CONNECTION TMUX TMUX_PANE XAUTHORITY"
    ${sudoer_id} ALL=(ALL) NOPASSWD: ALL
    | SUDO

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => $config_group,
    ;

    '/etc/sudoers.d':
      ensure => directory,
      mode   => $config_dir_mode,
    ;

    '/etc/sudoers.d/nest':
      content => $sudoer_content,
    ;

    # XXX Cleanup
    ['/etc/sudoers.d/10_env', '/etc/sudoers.d/10_wheel']:
      ensure => absent,
    ;
  }
}
