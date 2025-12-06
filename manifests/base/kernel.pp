class nest::base::kernel {
  Nest::Lib::Kconfig {
    config => '/usr/src/linux/.config',
  }

  $arch = $facts['profile']['architecture'] ? {
    'amd64' => 'x86_64',
    default => $facts['profile']['architecture'],
  }

  $nest::kernel_config.each |$config, $value| {
    nest::lib::kconfig { $config:
      value => $value,
    }
  }

  if $nest::bootloader == 'systemd' {
    nest::lib::kconfig { ['CONFIG_EFI', 'CONFIG_EFI_STUB']:
      value => y,
    }
  }

  nest::lib::package { 'sys-devel/bc':
    ensure => installed,
    before => Nest::Lib::Build['kernel'],
  }

  nest::lib::src_repo { '/usr/src/linux':
    url => 'https://gitlab.joyfullee.me/nest/forks/linux.git',
    ref => $nest::kernel_tag,
  }
  ~>
  nest::lib::build { 'kernel':
    args      => 'LOCALVERSION= olddefconfig all modules_install',
    defconfig => $nest::kernel_defconfig,
    dir       => '/usr/src/linux',
    llvm      => $nest::kernel_llvm,
    makeargs  => "ARCH=${arch} DTC_FLAGS='-@'",
    notify    => Class['nest::base::dracut'], # in case module-rebuild is noop
  }
  ->
  exec { 'module-rebuild':
    command     => '/usr/bin/emerge --buildpkg n --usepkg n @module-rebuild',
    noop        => !$facts['build'] or str2bool($facts['skip_module_rebuild']),
    refreshonly => true,
    timeout     => 0,
    subscribe   => Nest::Lib::Build['kernel'],
    notify      => Class['nest::base::dracut'],
  }

  # Sources w/o config, just like a provided package
  file_line { 'package.provided-kernel':
    path    => '/etc/portage/profile/package.provided',
    line    => "sys-kernel/vanilla-sources-${nest::kernel_version.regsubst('-', '_')}",
    match   => '^sys-kernel/vanilla-sources-',
    require => Nest::Lib::Src_repo['/usr/src/linux'],
    before  => Nest::Lib::Build['kernel'],
  }
}
