define nest::lib::package (
  Boolean                  $binpkg   = true,
  Boolean                  $build    = true,
  String                   $ensure   = 'installed',
  Hash                     $env      = {},
  String                   $package  = $name,
  Boolean                  $unstable = false,
  Optional[Nest::UseFlags] $use      = undef,
  Boolean                  $world    = true,
) {
  if !$binpkg and $ensure != 'absent' {
    if defined(Package_env[$name]) {
      Package_env <| title == $name |> {
        env    +> 'no-buildpkg.conf',
        before +> Package[$name],
        tag    +> 'profile',
      }
    } else {
      package_env { $name:
        name   => $package,
        env    => 'no-buildpkg.conf',
        before => Package[$name],
        tag    => 'profile',
      }
    }

    $usepkg_option = [{ '--usepkg' => 'n' }]
  } else {
    $usepkg_option = []
  }

  unless $env.empty {
    nest::lib::package_env { $name:
      name => $package,
      env  => $env,
    }
  }

  if $unstable {
    package_accept_keywords { $package:
      before => Package[$name],
      tag    => 'profile',
    }
  }

  $use_ensure = $use ? {
    undef   => 'absent',
    default => 'present',
  }

  nest::lib::package_use { $name:
    ensure => $use_ensure,
    name   => $package,
    use    => $use,
  }

  if $world {
    $oneshot_option = []
    $world_ensure   = $ensure ? {
      'absent' => 'absent',
      default  => 'present',
    }
  } else {
    $oneshot_option = ['--oneshot']
    $world_ensure   = 'absent'
  }

  package { $name:
    ensure          => $ensure,
    install_options => $usepkg_option + $oneshot_option,
    name            => $package,
    noop            => !$build,
  }
  ->
  file_line { "emerge-select-${name}":
    ensure => $world_ensure,
    path   => '/var/lib/portage/world',
    line   => $package,
    noop   => !$build,
    tag    => 'profile',
  }
}
