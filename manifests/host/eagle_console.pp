class nest::host::eagle_console {
  include nest::tool::arduino

  # Avoid using UART on this node
  file_line {
    default:
      path   => '/usr/src/u-boot/board/raspberrypi/rpi/rpi.env',
      notify => Exec['uboot-build'],
    ;

    'u-boot-rpi.env-stdin':
      line  => 'stdin=usbkbd',
      match => '^stdin=',
    ;

    'u-boot-rpi.env-stdout':
      line  => 'stdout=vidconsole',
      match => '^stdout=',
    ;

    'u-boot-rpi.env-stderr':
      line  => 'stderr=vidconsole',
      match => '^stderr=',
    ;
  }

  # Try to reject UART input stopping autoboot
  nest::lib::kconfig {
    default:
      config => '/usr/src/u-boot/.config';
    'CONFIG_AUTOBOOT_KEYED':
      value => y;
    'CONFIG_AUTOBOOT_KEYED_CTRLC':
      value => y,
    ;
  }

  nest::lib::package { [
    'dev-libs/libgpiod',
    'net-dialup/minicom',
  ]:
    ensure => installed,
  }


  # Deploy Arduino sketch
  unless $facts['is_container'] {
    Exec {
      cwd         => '/root',
      environment => ['HOME=/root'],
      require     => Class['nest::tool::arduino'],
    }

    file { '/root/PowerSupplyControl':
      ensure  => directory,
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      source  => 'puppet:///modules/nest/arduino/PowerSupplyControl',
      recurse => true,
    }
    ~>
    exec { 'arduino-cli-compile-PowerSupplyControl':
      command     => '/usr/local/bin/arduino-cli compile --fqbn arduino:avr:uno PowerSupplyControl',
      refreshonly => true,
    }
    ~>
    exec { 'arduino-cli-upload-PowerSupplyControl':
      command     => '/usr/local/bin/arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:uno PowerSupplyControl',
      refreshonly => true,
    }
  }
}
