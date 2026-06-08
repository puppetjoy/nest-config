define nest::lib::package_use (
  Enum['present', 'absent'] $ensure  = 'present',
  String                    $package = $name,
  Optional[Nest::UseFlags]  $use     = undef,
) {
  package_use { $name:
    ensure => $ensure,
    name   => $package,
    use    => $use,
    tag    => 'profile',
  }

  if defined(Package[$name]) {
    exec { "emerge-newuse-${name}":
      command     => "/usr/bin/emerge -N ${package}",
      timeout     => 0,
      refreshonly => true,
    }

    Package_use[$name]
    ~> Exec["emerge-newuse-${name}"]
    ~> Package[$name]
  }
}
