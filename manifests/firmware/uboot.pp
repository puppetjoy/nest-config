class nest::firmware::uboot {
  unless $nest::uboot_tag {
    fail("'uboot_tag' is not set")
  }

  Nest::Lib::Kconfig {
    config => '/usr/src/u-boot/.config',
  }

  $nest::uboot_config.each |$setting, $value| {
    nest::lib::kconfig { $setting:
      value => $value,
    }
  }

  $env_is_in_spi_flash = $facts['profile']['platform'] ? {
    'radxazero'    => undef, # setting not available
    /^raspberrypi/ => undef, # setting not available
    default        => n,
  }

  nest::lib::kconfig {
    'CONFIG_BOOTDELAY':
      value => $nest::boot_menu_delay;

    # Always use default environment to avoid divergence
    'CONFIG_ENV_IS_NOWHERE':
      value => y;
    'CONFIG_ENV_IS_IN_FAT':
      value => n;
    'CONFIG_ENV_IS_IN_SPI_FLASH':
      value => $env_is_in_spi_flash,
    ;
  }

  if $nest::uboot_tag =~ /^radxa\// {
    nest::lib::kconfig { 'CONFIG_DISABLE_CONSOLE':
      value => n,
    }

    # nest::lib::packages doesn't play nice with sloted packages
    nest::lib::package { [
      'dev-lang/python:2.7',
      'sys-apps/dtc',
    ]:
      ensure => installed,
      before => Exec['uboot-build'],
    }
  }

  case $facts['profile']['platform'] {
    'milkv-mars': {
      # See: https://docs.u-boot.org/en/latest/board/starfive/milk-v_mars.html
      $build_options = 'OPENSBI=../opensbi/build/platform/generic/firmware/fw_dynamic.bin'
    }

    /^(pinebookpro|rockpro64|rock4|rock5)$/: {
      $build_options = $facts['profile']['platform'] ? {
        'rock5' => "BL31=../rkbin/bin/rk35/rk3588_bl31_v1.47.elf \
                    ROCKCHIP_TPL=../rkbin/bin/rk35/rk3588_ddr_lp4_2112MHz_lp5_2400MHz_v1.18.bin",
        default => 'BL31=../arm-trusted-firmware/build/rk3399/release/bl31/bl31.elf',
      }

      # Rockchip defaults to uncommon 1.5 Mbps
      nest::lib::kconfig { 'CONFIG_BAUDRATE':
        value => 115200,
      }

      nest::lib::package { 'dev-python/pyelftools':
        ensure => installed,
        before => Exec['uboot-build'],
      }
    }

    /^(pine64|sopine)$/: {
      $build_options = 'BL31=../arm-trusted-firmware/build/sun50i_a64/release/bl31.bin SCP=/dev/null'
    }

    default: {
      $build_options = ''
    }
  }

  case $build_options {
    /arm-trusted-firmware/: {
      Class['nest::firmware::arm']
      ~> Nest::Lib::Build['uboot']
    }

    /opensbi/: {
      Class['nest::firmware::opensbi']
      ~> Nest::Lib::Build['uboot']
    }

    /rkbin/: {
      Class['nest::firmware::rockchip']
      ~> Nest::Lib::Build['uboot']
    }
  }

  nest::lib::package { 'dev-lang/swig':
    ensure => installed,
    before => Nest::Lib::Build['uboot'],
  }

  nest::lib::src_repo { '/usr/src/u-boot':
    url => 'https://gitlab.james.tl/nest/forks/u-boot.git',
    ref => $nest::uboot_tag,
  }
  ~>
  nest::lib::build { 'uboot':
    args      => $build_options,
    defconfig => $nest::uboot_defconfig,
    dir       => '/usr/src/u-boot',
  }
}
