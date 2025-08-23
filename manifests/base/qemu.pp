class nest::base::qemu {
  if ($facts['hypervisors'] and $facts['hypervisors']['kvm'])
  or ($facts['profile'] and $facts['profile']['platform'] == 'live') {
    $qemu_guest_agent_ensure = installed
  } else {
    $qemu_guest_agent_ensure = absent
  }

  $package_name = $facts['os']['family'] ? {
    'Gentoo'  => 'app-emulation/qemu-guest-agent',
    'windows' => 'virtio-drivers',
    default   => undef,
  }

  if $package_name {
    package { $package_name:
      ensure => $qemu_guest_agent_ensure,
    }
  }
}
