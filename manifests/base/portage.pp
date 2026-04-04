class nest::base::portage {
  tag 'profile'

  class { 'portage':
    eselect_ensure => installed,
  }

  # Disable package rebuilds (from portage module) during build stages
  if $facts['build'] and $facts['build'] =~ /^stage\d+$/ {
    Exec <| title == 'changed_makeconf' |> {
      noop => true,
    }
  }

  # Remove unused directories created by Class[portage]
  File <|
    title == '/etc/portage/package.keywords' or
    title == '/etc/portage/postsync.d'
  |> {
    ensure => absent,
    force  => true,
  }

  # Purge all other unmanaged configs
  File <|
    title == '/etc/portage/package.mask' or
    title == '/etc/portage/package.unmask' or
    title == '/etc/portage/package.use'
  |> {
    purge   => true,
    recurse => true,
    force   => true,
  }

  file {
    default:
      ensure  => directory,
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      purge   => true,
      recurse => true,
      force   => true,
    ;

    [
      '/etc/portage/env',
      '/etc/portage/package.accept_keywords',
      '/etc/portage/package.env',
      '/etc/portage/profile',
      '/etc/portage/profile/package.use.force',
      '/etc/portage/profile/package.use.mask',
    ]:
      # use defaults
    ;

    [
      '/etc/portage/package.accept_keywords/default',
      '/etc/portage/package.env/default',
      '/etc/portage/package.mask/default',
      '/etc/portage/package.unmask/default',
      '/etc/portage/package.use/default',
      '/etc/portage/profile/package.provided',
    ]:
      ensure => file,
    ;

    '/etc/portage/patches':
      source => 'puppet:///modules/nest/portage/patches',
    ;
  }

  # Workaround https://bugs.gentoo.org/428262
  # pkg_pretend step makes initial distcc lockfile with wrong permissions
  file {
    "${facts['portage_portage_tmpdir']}/portage":
      ensure => directory,
      mode   => '0775',
      owner  => 'portage',
      group  => 'portage',
    ;

    [
      "${facts['portage_portage_tmpdir']}/portage/.distcc",
      "${facts['portage_portage_tmpdir']}/portage/.distcc/lock",
    ]:
      ensure => directory,
      mode   => '2775',
      owner  => 'root',
      group  => 'portage',
    ;

    "${facts['portage_portage_tmpdir']}/portage/.distcc/lock/cpu_localhost_0":
      ensure => file,
      mode   => '0664',
      owner  => 'portage',
      group  => 'portage',
    ;
  }


  #
  # make.conf
  #
  $makejobs_memory     = ceiling($facts['memory']['system']['total_bytes'] / (512.0 * 1024 * 1024))
  $distcc_hosts        = $nest::distcc_hosts.delete("${trusted['certname']}.nest")
  $makejobs_distcc     = $distcc_hosts.reduce($nest::concurrency) |$memo, $host| { $memo + $host[1] }
  $makejobs            = min($makejobs_memory, $makejobs_distcc)
  $mergejobs           = $nest::concurrency
  $loadlimit           = $nest::concurrency + 1
  $emerge_default_opts = pick($facts['emerge_default_opts'], "--jobs=${mergejobs} --load-average=${loadlimit}")
  $makeopts            = pick($facts['makeopts'], "-j${makejobs} -l${loadlimit}")

  $features = $facts['is_container'] ? {
    true    => ['distcc', '-ipc-sandbox', '-pid-sandbox', '-network-sandbox', '-usersandbox'],
    default => ['distcc'],
  }

  portage::makeconf {
    'emerge_default_opts':
      content => "\${EMERGE_DEFAULT_OPTS} ${emerge_default_opts}",
    ;

    'features':
      content => $features,
      require => Class['nest::base::distcc'],
    ;

    'makeopts':
      content => $makeopts,
    ;
  }

  $use = $nest::use.sort.unique

  unless empty($use) {
    portage::makeconf { 'use':
      content => $use.join(' '),
    }
  }

  # Don't timeout rebuilding packages
  Exec <| title == 'changed_makeconf' |> {
    timeout => 0,
  }



  #
  # Repositories
  #
  contain 'nest::lib::repos'

  nest::lib::repo {
    'gentoo':
      url     => 'https://gitlab.joyfullee.me/nest/gentoo/portage.git',
      default => true,
    ;

    'haskell':
      url      => 'https://gitlab.joyfullee.me/nest/gentoo/haskell.git',
      unstable => true,
    ;

    'nest':
      url      => 'https://gitlab.joyfullee.me/nest/overlay.git',
      unstable => true,
    ;
  }

  file { '/etc/portage/package.unmask/ghc-9.8':
    ensure  => link,
    target  => '/var/db/repos/haskell/scripts/package.unmask/ghc-9.8',
    require => Nest::Lib::Repo['haskell'],
  }



  #
  # Package environments and properties
  #

  # Used by nest::lib::package
  file { '/etc/portage/env/no-buildpkg.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => "FEATURES=\"-buildpkg\"\n",
  }

  # Use lighter debug flags on big packages
  $cflags_light_debug = regsubst($facts['portage_cflags'], '(\s?)(-g(gdb\d?)?)(\s|$)', '\1\21\4')
  if $cflags_light_debug != $facts['portage_cflags'] {
    file { '/etc/portage/env/light-debug.conf':
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => "CFLAGS=\"${cflags_light_debug}\"\nCXXFLAGS=\"\${CFLAGS}\"\n",
    }
    ->
    package_env { 'net-libs/webkit-gtk':
      env => 'light-debug.conf',
    }
  }

  # xvid incorrectly passes `-mcpu` as `-mtune` which doesn't accept `+crypto`
  $cflags_no_crypto = regsubst($facts['portage_cflags'], '\+crypto', '')
  if $cflags_no_crypto != $facts['portage_cflags'] {
    file { '/etc/portage/env/no-crypto.conf':
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => "CFLAGS=\"${cflags_no_crypto}\"\nCXXFLAGS=\"\${CFLAGS}\"\n",
    }
    ->
    package_env { 'media-libs/xvid':
      env => 'no-crypto.conf',
    }
  }

  if $facts['is_container'] {
    file { '/etc/portage/profile/profile.bashrc':
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => "DONT_MOUNT_BOOT=1\n",
    }
  }


  # Create portage package properties rebuild affected packages
  create_resources(package_accept_keywords, $nest::package_keywords, {
    'accept_keywords' => '~*',
    'before'          => Class['portage'],
  })
  create_resources(package_env, $nest::package_env, {
    'before' => Class['portage']
  })
  create_resources(package_unmask, $nest::package_unmask, {
    'before' => Class['portage']
  })
  create_resources(package_use, $nest::package_use, {
    'before' => Class['portage'],
    'tag'    => 'profile',
  })

  # Purge unmanaged portage package properties
  resources { [
    'package_accept_keywords',
    'package_env',
    'package_mask',
    'package_unmask',
    'package_use',
  ]:
    purge  => true,
    before => Class['portage'],
  }

  # Portage should be configured before any packages are installed/changed
  Class['nest::base::portage']
  -> Package <|
    (provider == 'portage' or provider == undef) and
    title != 'dev-vcs/git' and
    title != 'sys-devel/distcc'
  |>
}
