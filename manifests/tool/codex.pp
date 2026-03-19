class nest::tool::codex {
  case $facts['os']['family'] {
    'Gentoo': {
      include 'nodejs'

      $codex_package = '@openai/codex'
      $codex_target = '/opt/codex'

      file { $codex_target:
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }
      ->
      exec { 'npm_install_codex':
        command     => "${nodejs::npm_path} install ${codex_package}@latest",
        unless      => "${nodejs::npm_path} ls ${codex_package} --depth=0 >/dev/null 2>&1 && ${nodejs::npm_path} outdated ${codex_package} --depth=0 >/dev/null 2>&1",
        cwd         => $codex_target,
        environment => ['HOME=/root'],
        require     => Class['nodejs'],
      }
      ->
      file { '/usr/local/bin/codex':
        ensure => link,
        target => "${codex_target}/node_modules/@openai/codex/bin/codex.js",
      }

      # Common utilities invoked by codex
      nest::lib::package { [
        'dev-python/uv',
        'sys-apps/ripgrep',
      ]:
        ensure => present,
      }
    }

    'Darwin': {
      package { 'codex':
        ensure => latest,
      }

      package { 'codex-app':
        ensure => installed, # auto updates
      }
    }
  }
}
