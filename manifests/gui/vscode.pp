class nest::gui::vscode {
  if $facts['profile']['architecture'] in ['amd64', 'arm', 'arm64'] {
    $code_wrapper = @("WRAPPER")
      #!/bin/bash
      exec /opt/vscode/bin/code \
          --force-device-scale-factor=${nest::text_scaling_factor} \
          "$@"
      | WRAPPER

    nest::lib::package { 'app-editors/vscode':
      ensure => installed,
    }
    ->
    file { '/usr/bin/code':
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => $code_wrapper,
    }
  }
}
