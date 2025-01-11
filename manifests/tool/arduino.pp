class nest::tool::arduino (
  Stdlib::Filesource $cli_source,
) {
  Exec {
    environment => ['HOME=/root'],
  }

  # See https://arduino.github.io/arduino-cli/1.1/installation/
  archive { '/var/tmp/arduino-cli.tar.gz':
    creates       => '/usr/local/bin/arduino-cli',
    extract       => true,
    extract_flags => '-x arduino-cli -f',
    extract_path  => '/usr/local/bin',
    source        => $cli_source,
  }
  ~>
  exec { 'arduiro-cli-core-update-index':
    command     => '/usr/local/bin/arduino-cli core update-index',
    refreshonly => true,
  }
  ->
  exec { 'arduiro-cli-core-install-avr':
    command => '/usr/local/bin/arduino-cli core install arduino:avr',
    timeout => '3600', # 1 hour
    unless  => '/usr/local/bin/arduino-cli core list | /bin/grep "^arduino:avr "',
  }
}
