class nest::gui::input {
  # Fix horizontal scrolling on MX Master 3S
  $libinput_quirks = @(QUIRKS)
    [Logitech Bolt Receiver]
    MatchVendor=0x046D
    MatchProduct=0xC548
    ModelInvertHorizontalScrolling=1
    | QUIRKS

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/libinput':
      ensure  => directory,
    ;

    '/etc/libinput/local-overrides.quirks':
      content => $libinput_quirks,
    ;
  }
}
