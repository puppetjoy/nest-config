class nest::tool::vagrant {
  nest::lib::package { 'app-emulation/vagrant':
    ensure => installed,
  }
  ->
  exec { 'vagrant-plugin-install-libvirt':
    command => '/usr/bin/vagrant plugin install vagrant-libvirt',
    unless  => '/usr/bin/vagrant plugin list | /usr/bin/grep -q vagrant-libvirt',
    user    => 'james',
  }
}
