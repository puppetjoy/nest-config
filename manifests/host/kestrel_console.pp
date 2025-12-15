class nest::host::kestrel_console {
  $udev_rule_content = @(UDEV)
    # CP2102 (10c4:ea60, serial 0001): force known-good tty settings on add
    ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyUSB*", \
      ENV{ID_BUS}=="usb", ENV{ID_VENDOR_ID}=="10c4", ENV{ID_MODEL_ID}=="ea60", \
      ENV{ID_SERIAL_SHORT}=="0001", \
      RUN+="/bin/stty -F /dev/%k 115200 raw -echo -ixon -ixoff -crtscts"
    | UDEV

  file { '/etc/udev/rules.d/99-cp2102-stty.rules':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $udev_rule_content,
  }
}
