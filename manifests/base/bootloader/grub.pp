class nest::base::bootloader::grub {
  tag 'boot'
  tag 'kernel'

  $grub_use = $facts['profile']['architecture'] ? {
    'amd64' => ['grub_platforms_efi-64', 'grub_platforms_pc', 'libzfs', 'truetype'],
    default => ['grub_platforms_efi-64', 'libzfs', 'truetype'],
  }

  nest::lib::package_use { 'sys-boot/grub':
    use => $grub_use,
  }

  if $facts['mountpoints']['/boot'] or ($facts['profile']['platform'] == 'live' and $facts['is_container'] and !$facts['build']) {
    $grub_device = $facts['profile']['platform'] == 'live' ? {
      true    => "live:LABEL=${trusted['certname'].upcase}",
      default => 'zfs:AUTO',
    }

    if $facts['profile']['platform'] or $facts['virtual'] == 'kvm' {
      $gfxmode    = 'GRUB_GFXMODE=1024x768'
      $gfxpayload = 'GRUB_GFXPAYLOAD_LINUX=keep'
    } else {
      $gfxmode    = '#GRUB_GFXMODE=640x480'
      $gfxpayload = '#GRUB_GFXPAYLOAD_LINUX='
    }

    $font = "ter-x${nest::console_font_size}b"

    file_line {
      default:
        path    => '/etc/default/grub',
        require => Package['sys-boot/grub'],
        notify  => Exec['grub-mkconfig'],
      ;

      'grub-set-distributor':
        line  => 'GRUB_DISTRIBUTOR="Nest"',
        match => '^#?GRUB_DISTRIBUTOR=',
      ;

      'grub-set-default':
        line  => "GRUB_DEFAULT=\"linux-${nest::kernel_version}-advanced-${grub_device}\"",
        match => '^#?GRUB_DEFAULT=',
      ;

      'grub-set-timeout':
        line  => "GRUB_TIMEOUT=${nest::boot_menu_delay}",
        match => '^#?GRUB_TIMEOUT=',
      ;

      'grub-set-kernel-cmdline':
        line  => "GRUB_CMDLINE_LINUX=\"${nest::base::bootloader::kernel_cmdline}\"",
        match => '^#?GRUB_CMDLINE_LINUX=',
      ;

      'grub-set-gfxmode':
        line  => $gfxmode,
        match => '^#?GRUB_GFXMODE',
      ;

      'grub-set-gfxpayload':
        line  => $gfxpayload,
        match => '^#?GRUB_GFXPAYLOAD_LINUX',
      ;

      'grub-disable-linux-uuid':
        line  => 'GRUB_DISABLE_LINUX_UUID=true',
        match => '^#?GRUB_DISABLE_LINUX_UUID=',
      ;

      'grub-disable-linux-partuuid':
        line  => 'GRUB_DISABLE_LINUX_PARTUUID=true',
        match => '^#?GRUB_DISABLE_LINUX_PARTUUID=',
      ;

      'grub-disable-recovery':
        line  => 'GRUB_DISABLE_RECOVERY=true',
        match => '^#?GRUB_DISABLE_RECOVERY=',
      ;

      'grub-disable-submenu':
        line  => 'GRUB_DISABLE_SUBMENU=y',
        match => '^#?GRUB_DISABLE_SUBMENU=',
      ;

      'grub-set-device':
        line  => "GRUB_DEVICE=${grub_device}",
        match => '^#?GRUB_DEVICE=',
      ;

      'grub-set-fs':
        line  => 'GRUB_FS=',
        match => '^#?GRUB_FS=',
      ;

      'grub-set-font':
        line  => "GRUB_FONT=/boot/grub/fonts/${font}.pf2",
        match => '^#?GRUB_FONT=',
      ;
    }

    file { '/boot/grub':
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    }

    file { [
      '/boot/grub/fonts',
      '/boot/grub/layouts',
    ]:
      ensure  => directory,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      recurse => true,
      purge   => true,
    }

    exec { 'grub-mkfont':
      command => "/usr/bin/grub-mkfont -o /boot/grub/fonts/${font}.pf2 /usr/share/fonts/terminus/${font}.pcf.gz",
      creates => "/boot/grub/fonts/${font}.pf2",
      require => [
        Package['sys-boot/grub'],
        File['/boot/grub/fonts'],
      ],
    }

    file { "/boot/grub/fonts/${font}.pf2":
      require => Exec['grub-mkfont'],
    }

    file { '/boot/grub/layouts/dvorak.gkb':
      mode   => '0644',
      owner  => 'root',
      group  => 'root',
      source => 'puppet:///modules/nest/keymaps/dvorak.gkb',
    }

    # Install stuff normally handled by kernel-install(8)
    file { "/boot/vmlinuz-${nest::kernel_version}":
      source => $nest::base::bootloader::kernel_image,
    }
    ~>
    exec { 'dracut':
      command     => "/usr/bin/dracut --force --kver ${nest::kernel_version}",
      refreshonly => true,
      subscribe   => Class['nest::base::dracut'],
    }
    ~>
    exec { 'grub-mkconfig':
      command     => '/usr/sbin/grub-mkconfig -o /boot/grub/grub.cfg',
      refreshonly => true,
      require     => Exec['grub-mkfont'],
    }

    if $facts['profile']['platform'] == 'live' {
      exec { 'grub-modify-live-config':
        command     => '/bin/sed -i -r "/insmod ext2/,/search/d" /boot/grub/grub.cfg',
        refreshonly => true,
        subscribe   => Exec['grub-mkconfig'],
      }

      # Make certain files user readable for unprivileged live CD creation
      file {
        default:
          mode  => '0644',
          owner => 'root',
          group => 'root',
        ;

        '/boot/grub/grub.cfg':
          require => Exec['grub-mkconfig'],
        ;

        "/boot/initramfs-${nest::kernel_version}.img":
          require => Exec['dracut'],
        ;
      }
    }

    $facts['partitions'].each |$partition, $attributes| {
      $disk = regsubst($partition, 'p?(art)?\d+$', '')

      if "${::trusted['certname']}-" in $attributes['partlabel'] {
        $grub_install_command_efi = @("GRUB_EFI")
          /bin/mkdir /boot/efi &&
          /bin/mount ${partition} /boot/efi &&
          /usr/sbin/grub-install --target=x86_64-efi --removable --modules=part_gpt &&
          /bin/umount /boot/efi &&
          /bin/rm -rf /boot/efi
          | GRUB_EFI

        $grub_install_command_bios = "/usr/sbin/grub-install --target=i386-pc --modules=part_gpt ${disk}"

        $grub_install_command = $attributes['partlabel'] ? {
          /-efi/  => $grub_install_command_efi,
          /-bios/ => $grub_install_command_bios,
          default => undef,
        }

        if $grub_install_command {
          exec { "grub-install-${disk}":
            command     => $grub_install_command,
            refreshonly => true,
            require     => Package['sys-boot/grub'],
            before      => File['/boot/grub'],
          }
        }
      }
    }
  }
}
