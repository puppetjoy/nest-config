class nest::gui::vscode {
  if $facts['profile']['architecture'] in ['amd64', 'arm', 'arm64'] {
    $code_wrapper = @("WRAPPER")
      #!/bin/bash
      exec /opt/vscode/bin/code \
          --force-device-scale-factor=${nest::text_scaling_factor} \
          --ignore-gpu-blocklist \
          --ozone-platform=x11 \
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
