define nest::lib::package_use (
  Boolean                   $binpkg  = true,
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
    $usepkg_option = $binpkg ? {
      true    => '',
      default => ' --usepkg=n',
    }

    exec { "emerge-newuse-${name}":
      command     => "/usr/bin/emerge -N${usepkg_option} ${package}",
      timeout     => 0,
      refreshonly => true,
    }

    Package_use[$name]
    ~> Exec["emerge-newuse-${name}"]
    ~> Package[$name]
  }
}
