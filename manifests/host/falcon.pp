class nest::host::falcon {
  nest::lib::toolchain {
    [
      'aarch64-unknown-linux-gnu',
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
}
