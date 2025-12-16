class nest::firmware::amlogic {
  $board = $facts['profile']['platform'] ? {
    'radxazero' => 'radxa-zero',
    default     => fail("Unsupported platform ${facts['profile']['platform']}"),
  }

  nest::lib::src_repo { '/usr/src/fip':
    url => 'https://gitlab.joyfullee.me/nest/forks/fip.git',
    ref => 'radxa',
  }
  ~>
  nest::lib::build { 'amlogic-firmware':
    args      => "distclean fip BOARD=${board} UBOOT_BIN=/usr/src/u-boot/u-boot.bin",
    dir       => '/usr/src/fip',
    makeargs  => '-j1', # FIP build system is not parallel-safe
    subscribe => Class['nest::firmware::uboot'],
  }
}
