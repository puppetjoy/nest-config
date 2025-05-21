class nest::base::bootloader::uroot {
  contain 'nest::base::bootloader::spec'
  include 'nest::base::kernel'

  unless $nest::uroot_branch {
    fail("'uroot_branch' is not set")
  }

  nest::lib::src_repo { '/usr/src/u-root':
    url => 'https://gitlab.james.tl/nest/forks/u-root.git',
    ref => $nest::uroot_branch,
  }
  ~>
  nest::lib::build { 'u-root':
    dir     => '/usr/src/u-root',
    command => [
      'CGO_ENABLED=0 go build',
      './u-root -uinitcmd="boot -remove= -reuse=" -o initramfs.cpio core boot',
    ],
  }

  # Build separate kernel image for u-root without custom config or modules to
  # provide stable fallback to older kernels
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
