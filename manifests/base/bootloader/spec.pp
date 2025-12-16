class nest::base::bootloader::spec {
  tag 'boot'
  tag 'kernel'

  if $facts['mountpoints']['/boot'] {
    # For nest::base::bootloader::kernel_cmdline
    include 'nest::base::bootloader'

    $loader_conf = @("LOADER_CONF")
      default ${facts['machine_id']}-${nest::kernel_version}.conf
      timeout ${nest::boot_menu_delay}
      | LOADER_CONF

    file {
      '/boot/loader':
        ensure => directory;
      '/boot/loader/loader.conf':
        content => $loader_conf,
      ;
    }

    file {
      default:
        mode  => '0644',
        owner => 'root',
        group => 'root',
      ;

      "/boot/${facts['machine_id']}":
        ensure => directory,
        before => Exec['kernel-install'],
      ;

      '/etc/kernel':
        ensure => directory,
      ;

      '/etc/kernel/cmdline':
        content => "${nest::base::bootloader::kernel_cmdline}\n",
        notify  => Exec['kernel-install'],
      ;
    }

    # XXX USE flags set in profile
    # Remove after Mar 2024 build deployed
    nest::lib::package { 'sys-kernel/installkernel':
      use   => ['dracut', 'systemd-boot'],
      world => false,
    }
    ~>
    exec { 'kernel-install':
      command     => "/usr/bin/kernel-install add ${nest::kernel_version} ${nest::base::bootloader::kernel_image}",
      refreshonly => true,
      timeout     => 0,
      subscribe   => Class['nest::base::dracut'],
    }

    # Legacy extlinux config
    if $facts['profile']['platform'] in [] {
      $extlinux_conf = @("EXTLINUX")
        DEFAULT Nest (${nest::kernel_version})
        TIMEOUT ${nest::boot_menu_delay}
        INCLUDE /extlinux/entries.conf
        | EXTLINUX

      file {
        default:
          mode  => '0755',
          owner => 'root',
          group => 'root',
        ;

        '/boot/extlinux':
          ensure => directory,
        ;

        '/boot/extlinux/extlinux.conf':
          content => $extlinux_conf,
        ;
      }

      $entries_awk = @(AWK)
        /^title\s/          { if (NR != 1) { print "" } $1 = "LABEL"; title = $0; next }
        /^version\s/        { printf "%s (%s)\n DEVICETREEDIR /\n", title, $2; next }
        /^options\s/        { $1 = " APPEND"; print; next }
        /^(linux|initrd)\s/ { printf " %s %s\n", toupper($1), $2 }
        AWK

      exec { 'generate-extlinux-entries':
        command     => "/usr/bin/awk ${entries_awk.shellquote} /boot/loader/entries/*.conf > /boot/extlinux/entries.conf",
        refreshonly => true,
        subscribe   => Exec['kernel-install'],
        require     => File['/boot/extlinux'],
        provider    => shell,
      }
    } else {
      file { '/boot/extlinux':
        ensure => absent,
        force  => true,
      }
    }
  }
}
