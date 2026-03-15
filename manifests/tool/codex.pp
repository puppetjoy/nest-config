class nest::tool::codex {
  case $facts['os']['family'] {
    'Gentoo': {
      include 'nodejs'

      file { '/opt/codex':
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }
      ->
      nodejs::npm { '@openai/codex':
        ensure => 'latest',
        target => '/opt/codex',
      }
      ->
      file { '/usr/local/bin/codex':
        ensure => link,
        target => '/opt/codex/node_modules/@openai/codex/bin/codex.js',
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
