class nest::app::bitwarden {
  include 'nodejs'

  # Don't prune USE flags config set by nodejs module
  file { '/etc/portage/package.use/nodejs-flags':
    ensure  => file,
    require => Class['nodejs'],
  }

  file { '/opt/bitwarden':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
  }
  ->
  nodejs::npm { '@bitwarden/cli':
    target => '/opt/bitwarden',
  }
  ->
  file { '/opt/bitwarden/bw':
    ensure => link,
    target => '/opt/bitwarden/node_modules/@bitwarden/cli/build/bw.js',
  }
}
