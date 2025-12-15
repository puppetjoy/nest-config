class nest::host::kestrel_console {
  $udev_rule_content = @(UDEV)
    ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyUSB*", \
      RUN+="/bin/stty -F /dev/%k 115200 raw -echo -ixon -ixoff -crtscts"
    | UDEV

  file { '/etc/udev/rules.d/99-ttyusb-raw.rules':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $udev_rule_content,
  }
}
