class nest::tool::vscode {
  case $facts['os']['family'] {
    'Gentoo': {
      if $facts['profile']['architecture'] in ['amd64', 'arm64'] {
        $code_wrapper = @("WRAPPER")
          #!/bin/bash
          exec /opt/vscode/bin/code \
              --force-device-scale-factor=${nest::gui_scaling_factor} \
              --reuse-window \
              "$@"
          | WRAPPER

        nest::lib::package { 'app-editors/vscode':
          ensure => installed,
        }
        ->
        file {
          '/usr/bin/code':
            mode    => '0755',
            owner   => 'root',
            group   => 'root',
            content => $code_wrapper,
          ;

          '/usr/bin/vscode':
            ensure => link,
            target => '/usr/bin/code',
          ;
        }
      }
    }

    'Darwin': {
      package { 'visual-studio-code':
        ensure => installed,
      }
    }
  }
}
