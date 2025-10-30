class nest::base::bootloader::uroot {
  contain 'nest::base::bootloader::spec'
  include 'nest::base::kernel'

  unless $nest::uroot_tag {
    fail("'uroot_tag' is not set")
  }

  $bootcmd = 'boot -remove= -reuse='
  if $nest::uroot_delay {
    $bootscript = "sleep ${nest::uroot_delay}; exec ${bootcmd}"
    $uinitcmd = "gosh -c ${bootscript.shellquote}"
  } else {
    $uinitcmd = $bootcmd
  }

  nest::lib::src_repo { '/usr/src/u-root':
    url => 'https://gitlab.james.tl/nest/forks/u-root.git',
    ref => $nest::uroot_tag,
  }
  ~>
  nest::lib::build { 'u-root':
    dir     => '/usr/src/u-root',
    command => [
      'CGO_ENABLED=0 go build',
      "./u-root -uinitcmd=${uinitcmd.shellquote} -o initramfs.cpio core boot",
    ],
  }

  # Build separate kernel image for u-root with basic config and no modules
  # to provide stable fallback to older kernels
  $nest::kernel_config.each |$setting, $value| {
    if $value and $value =~ /^Y$/ { # == is case insensitive
      nest::lib::kconfig { "u-root-${setting}":
        config  => '/usr/src/u-root-linux/.config',
        setting => $setting,
        value   => $value,
      }
    }
  }

  nest::lib::src_repo { '/usr/src/u-root-linux':
    url => 'https://gitlab.james.tl/nest/forks/linux.git',
    ref => $nest::kernel_tag,
  }
  ~>
  nest::lib::build { 'u-root-linux':
    args      => 'LOCALVERSION= olddefconfig Image',
    defconfig => $nest::kernel_defconfig,
    dir       => '/usr/src/u-root-linux',
    makeargs  => "ARCH=${nest::base::kernel::arch}",
  }
}
