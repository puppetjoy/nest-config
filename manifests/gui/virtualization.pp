class nest::gui::virtualization {
  nest::lib::package { [
    'app-emulation/virt-manager',
    'app-emulation/virt-viewer',
  ]:
    ensure => installed,
  }
}
