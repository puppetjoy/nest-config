class nest::app::hermes (
  Optional[String[1]]  $version     = undef,
  Stdlib::Absolutepath $install_dir = '/opt/hermes-agent',
) {
  case $facts['os']['family'] {
    'Gentoo': {
      $venv_dir     = "${install_dir}/venv"
      $venv_python  = "${venv_dir}/bin/python"
      $venv_pip     = "${venv_dir}/bin/pip"
      $package_spec = $version ? {
        undef   => 'hermes-agent',
        default => "hermes-agent==${version}",
      }

      $install_unless = $version ? {
        undef   => "${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\"",
        default => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('hermes-agent') == '${version}' else 1)\"",
      }

      nest::lib::package { [
        'dev-python/virtualenv',
        'sys-apps/ripgrep',
      ]:
        ensure => present,
      }

      file { $install_dir:
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }
      ->
      exec { 'create_hermes_venv':
        command => "/usr/bin/python3 -m virtualenv ${venv_dir}",
        creates => $venv_python,
        require => Nest::Lib::Package['dev-python/virtualenv'],
      }
      ->
      exec { 'install_hermes_agent':
        command     => "${venv_pip} install ${package_spec}",
        unless      => $install_unless,
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      }
      ->
      file { '/usr/local/bin/hermes':
        ensure => link,
        target => "${venv_dir}/bin/hermes",
      }

      exec { 'install_hermes_telegram_deps':
        command     => "${venv_pip} install 'python-telegram-bot[webhooks]==22.6'",
        unless      => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('python-telegram-bot') == '22.6' else 1)\"",
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
        require     => Exec['install_hermes_agent'],
      }

      nest::lib::package { 'media-video/ffmpeg':
        ensure => present,
      }
    }
  }
}
