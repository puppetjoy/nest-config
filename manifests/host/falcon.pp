class nest::host::falcon {
  nest::lib::toolchain {
    [
      'aarch64-unknown-linux-gnu',
      'armv6j-unknown-linux-gnueabihf',
      'armv7a-unknown-linux-gnueabihf',
      'riscv64-unknown-linux-gnu',
    ]:
      # use defaults
    ;

    'arm-none-eabi':
      gcc_only => true,
    ;
  }

  nest::lib::package { 'media-libs/libva-intel-media-driver':
    ensure => installed,
  }

  nest::lib::virtual_host { 'nest':
    docroot     => '/srv/www/nest.joyfullee.me',
    servername  => 'nest.joyfullee.me',
    ssl         => false,
    zfs_docroot => false,
  }

  nest::lib::external_service { 'http': }
}
