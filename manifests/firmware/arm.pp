class nest::firmware::arm {
  unless $nest::arm_firmware_tag {
    fail("'arm_firmware_tag' is not set")
  }

  nest::lib::toolchain { 'aarch64-none-elf':
    gcc_only => true,
    before   => Nest::Lib::Build['arm-trusted-firmware'],
  }

  if $nest::soc == 'rk3399' {
    nest::lib::toolchain { 'arm-none-eabi': # for the M0 coprocessor
      gcc_only => true,
      before   => Nest::Lib::Build['arm-trusted-firmware'],
    }
  }

  nest::lib::src_repo { '/usr/src/arm-trusted-firmware':
    url => 'https://gitlab.joyfullee.me/nest/forks/arm-trusted-firmware.git',
    ref => $nest::arm_firmware_tag,
  }
  ~>
  nest::lib::build { 'arm-trusted-firmware':
    args => "E=0 PLAT=${nest::soc}",
    dir  => '/usr/src/arm-trusted-firmware',
  }
}
