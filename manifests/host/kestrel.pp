class nest::host::kestrel {
  # Workaround usbnet hang at boot
  # See: https://gitlab.james.tl/nest/config/-/issues/64
  file { '/usr/local/bin/usb_resetter':
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
    source => 'puppet:///modules/nest/scripts/usb_resetter.py',
  }

  systemd::manage_unit { 'reset-usbnet-device@.service':
    unit_entry    => {
      'Description' => 'Reset USBNET device',
    },
    service_entry => {
      'Type'      => 'oneshot',
      'ExecStart' => '/usr/local/bin/usb_resetter -d %i --reset-device',
    },
    install_entry => {
      'WantedBy' => 'network.target',
    },
  }
  ->
  service { 'reset-usbnet-device@0525:a4a2':
    enable => true,
  }
}
