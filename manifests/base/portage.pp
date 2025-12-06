class nest::base::portage {
  tag 'profile'

  class { 'portage':
    eselect_ensure => installed,
  }

  # Disable package rebuilds (from portage module) during build
  if $facts['build'] {
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

  file { '/etc/portage/env/no-buildpkg.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => "FEATURES=\"-buildpkg\"\n",
  }

  # Workaround build problems when using distcc
  file { '/etc/portage/env/no-distcc.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => "FEATURES=\"-distcc\"\n",
  }
  ->
  package_env { [
    'sci-libs/lapack',  # fails to verify fortran
    'sys-apps/systemd', # fails to build systemd-boot
  ]:
    env => 'no-distcc.conf',
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

  # Workaround https://bugs.gentoo.org/918897
  # Also force crypto extensions off (which should be the default)
  if $facts['profile']['architecture'] == 'arm64' {
    $cflags_disable_crypto = regsubst($facts['portage_cflags'], '(cortex-a72)', '\\1+nocrypto')

    nest::lib::package_env { 'www-client/chromium':
      env => {
        'CFLAGS'   => "${cflags_disable_crypto} -fuse-ld=lld",
        'CXXFLAGS' => '${CFLAGS}', # lint:ignore:single_quote_string_with_variables
        'LDFLAGS'  => "${facts['portage_ldflags']} -fuse-ld=lld -Wl,--undefined-version",
      },
    }
  }

  # Workaround https://bugs.gentoo.org/666560
  if $facts['is_container'] and !$facts['profile']['architecture'] == 'amd64' {
    file { '/etc/portage/env/no-sandbox.conf':
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => "FEATURES=\"-sandbox\"\n",
    }
    ->
    package_env { [
      'app-containers/conmon',
      'app-containers/podman',
      'sys-cluster/kubectl',
      'sys-libs/glibc',
    ]:
      env => 'no-sandbox.conf',
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
