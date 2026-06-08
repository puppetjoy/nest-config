define nest::lib::src_repo (
  String  $url,
  String  $ref        = 'main',
  Boolean $submodules = false,
) {
  if $facts['build'] {
    vcsrepo { $name:
      ensure     => latest,
      provider   => git,
      source     => $url,
      revision   => $ref,
      submodules => $submodules,
      before     => File[$name],
    }
  }

  # For automatic dependencies
  file { $name:
    ensure => directory,
  }
}
