class nest::firmware::raspberrypi {
  # /boot is fat32
  File {
    mode  => undef,
    owner => undef,
    group => undef,
  }

  if $facts['profile']['platform'] =~ /^raspberrypi[34]$/ {
    nest::lib::package { 'sys-boot/raspberrypi-firmware':
      ensure => installed,
      before => File['/boot/config.txt'],
    }
  }

  file { '/boot/config.txt':
    content => epp('nest/raspberrypi/config.txt.epp'),
  }

  case $nest::bootloader {
    'systemd': {
      $uboot_ensure = present
      $uboot_source = '/usr/src/u-boot/u-boot.bin'
      $uroot_ensure = absent
      $uroot_image  = undef
      $uroot_source = undef

      Class['nest::firmware::uboot']
      -> File['/boot/u-boot.bin']
    }

    'u-root': {
      unless $facts['profile']['platform'] == 'raspberrypi5' {
        fail('u-root bootloader is only supported on raspberrypi5')
      }

      include nest::base::bootloader # safe for stage2

      $uboot_ensure = absent
      $uboot_source = undef
      $uroot_ensure = present
      $uroot_image  = '/usr/src/u-root-linux/arch/arm64/boot/Image'
      $uroot_source = '/usr/src/u-root/initramfs.cpio'

      Class['nest::base::bootloader::uroot']
      -> File['/boot/kernel_2712.img', '/boot/u-root.img']
    }
  }

  file {
    '/boot/u-boot.bin':
      ensure => $uboot_ensure,
      source => $uboot_source,
    ;

    '/boot/kernel_2712.img':
      ensure => $uroot_ensure,
      source => $uroot_image,
    ;

    '/boot/u-root.img':
      ensure => $uroot_ensure,
      source => $uroot_source,
    ;

    '/boot/cmdline.txt':
      ensure  => $uroot_ensure,
      content => "${nest::kernel_cmdline.filter |$arg| { $arg =~ /^console=/ }.join(' ')} maxcpus=1\n",
  }
}
