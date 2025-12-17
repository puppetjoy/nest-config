class nest::base::firmware {
  tag 'kernel'

  if $nest::dtb_file {
    $soc_vendor = dirname($nest::dtb_file)

    $dtb_root = $facts['profile']['platform'] ? {
      'beagleboneblack' => '/boot',
      'milkv-pioneer'   => '/boot/riscv64',
      /^raspberrypi/    => '/boot',
      default           => "/boot/${soc_vendor}",
    }

    file { $dtb_root:
      ensure => directory,
    }

    $dtb_dest   = "${dtb_root}/${basename($nest::dtb_file)}"
    $dtb_source = "/usr/src/linux/arch/${facts['profile']['architecture']}/boot/dts/${nest::dtb_file}"

    if $nest::dtb_overlay {
      $dtso_content = @("DTSO")
        /dts-v1/;
        /plugin/;

        ${nest::dtb_overlay}
        |-DTSO

      file { '/boot/nest.dtso':
        content => $dtso_content,
      }
      ~>
      exec { 'dtc-overlay':
        command     => '/usr/src/linux/scripts/dtc/dtc -O dtb -o /boot/nest.dtbo -b 0 -@ /boot/nest.dtso',
        refreshonly => true,
        require     => Class['nest::base::kernel'],
      }
      ~>
      exec { 'fdtoverlay':
        command     => "/usr/src/linux/scripts/dtc/fdtoverlay -i ${dtb_source} -o ${dtb_dest} /boot/nest.dtbo",
        refreshonly => true,
      }
    } else {
      file { [
        '/boot/nest.dtso',
        '/boot/nest.dtbo',
      ]:
        ensure => absent,
      }

      file { $dtb_dest:
        source  => $dtb_source,
        require => Class['nest::base::kernel'],
      }
    }

    if $nest::kernel_tag =~ /^raspberrypi\// {
      file { '/boot/overlays':
        source  => "/usr/src/linux/arch/${facts['profile']['architecture']}/boot/dts/overlays",
        links   => follow,
        recurse => true,
        purge   => true,
        force   => true,
        ignore  => ['.*', '*.dts', 'Makefile'],
        require => Class['nest::base::kernel'],
      }
    }
  }

  nest::lib::package { 'sys-kernel/linux-firmware':
    ensure => installed,
  }

  $files = {
    'linux/rtl_bt/rtl8723bs_config.bin'            => ['pine64'],
    'manjaro/brcm/BCM4345C5.hcd'                   => ['pinebookpro'],
    'plugable/brcm/BCM20702A1-0a5c-21e8.hcd'       => ['wellsburg'],
    'raspberrypi/brcm/BCM4345C0.hcd'               => ['raspberrypi3', 'raspberrypi5', 'rockpro64', 'rock4'],
    'raspberrypi/brcm/BCM4345C5.hcd'               => ['radxazero', 'raspberrypi4'],
    'raspberrypi/brcm/brcmfmac43456-sdio.bin'      => ['pinebookpro', 'radxazero', 'raspberrypi4'],
    'raspberrypi/brcm/brcmfmac43456-sdio.clm_blob' => ['pinebookpro', 'radxazero', 'raspberrypi4'],
    'raspberrypi/brcm/brcmfmac43456-sdio.txt'      => ['pinebookpro', 'radxazero', 'raspberrypi4'],
  }

  $files_categorized = $files.reduce([{}, {}]) |$memo, $file| {
    $present   = $memo[0]
    $absent    = $memo[1]
    $source    = $file[0]
    $platforms = $file[1]
    $target    = regsubst($file[0], '^[^/]*/', '')

    if $facts['profile']['platform'] in $platforms {
      [$present + { $target => $source }, $absent]
    } else {
      [$present, $absent + { $target => $source }]
    }
  }

  $files_present = $files_categorized[0]
  $files_absent  = $files_categorized[1] - $files_categorized[0]

  $files_present.each |$target, $source| {
    file { "/lib/firmware/${target}":
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      source  => "puppet:///modules/nest/firmware/${source}",

      # Makes the directory structure
      require => Package['sys-kernel/linux-firmware'],
    }
  }

  $files_absent.each |$target, $source| {
    file { "/lib/firmware/${target}":
      ensure => absent,
    }
  }

  # Update initramfs for all changes in this class
  Class['nest::base::firmware']
  ~> Class['nest::base::dracut']
}
