# @summary Build updated Gentoo Stage 3 images containing OpenVox
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param cpu Build for this CPU architecture
# @param build Build the image
# @param deploy Deploy the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param from_image Build starting from this image
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param qemu_user_targets CPU architectures to emulate
# @param registry Container registry to push to
# @param registry_username Username for registry
# @param registry_password Password for registry
# @param registry_password_var Environment variable for registry password
plan nest::build::stage0 (
  String           $container,
  String           $cpu,
  Boolean          $build                 = true,
  Boolean          $deploy                = false,
  Optional[String] $emerge_default_opts   = undef,
  String           $from_image            = "nest/stage0:${cpu}",
  Boolean          $init                  = true,
  Optional[String] $makeopts              = undef,
  Array[String]    $qemu_user_targets     = lookup('nest::build::qemu_user_targets', default_value => []),
  String           $registry              = lookup('nest::build::registry', default_value => 'localhost'),
  Optional[String] $registry_username     = lookup('nest::build::registry_username', default_value => undef),
  Optional[String] $registry_password     = lookup('nest::build::registry_password', default_value => undef),
  String           $registry_password_var = 'NEST_REGISTRY_PASSWORD',
) {
  $debug_volume = "${container}-debug"
  $repos_volume = "${container}-repos" # cached between builds
  $target = Target.new(name => $container, uri => "podman://${container}")
  $qemu_args = $qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')

  if $deploy {
    if $registry_username {
      $registry_password_env = system::env($registry_password_var)
      if $registry_password_env {
        $registry_password_real = $registry_password_env
      } elsif $registry_password {
        $registry_password_real = $registry_password
      } else {
        $registry_password_real = prompt('Registry password', 'sensitive' => true).unwrap
      }

      run_command("podman login --username=${registry_username} --password-stdin ${registry} <<< \$registry_password", 'localhost', 'Login to registry', _env_vars => {
        'registry_password' => $registry_password_real,
      })
    }
  }

  if $init {
    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')
    run_command("podman volume rm -f ${debug_volume}", 'localhost', 'Remove existing debug volume')

    # Use Nest DNS like the config image/CI runners, not Podman's public fallback.
    # Note: initial LANG applies to all downstream containers
    $podman_create_cmd = @("CREATE"/L)
      podman create \
      --dns=172.22.4.3 \
      --env=LANG \
      --init \
      --name=${container} \
      --pull=always \
      --volume=/nest:/nest \
      --volume=${debug_volume}:/usr/lib/debug \
      --volume=${repos_volume}:/var/db/repos \
      ${qemu_args} \
      ${from_image} \
      sleep infinity
      | CREATE

    run_command($podman_create_cmd, 'localhost', 'Create build container')
  }

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    $emerge_env = {
      'ACCEPT_KEYWORDS'     => '~*', # latest version on all architectures
      'DISTDIR'             => '/nest/portage/distfiles',
      'EMERGE_DEFAULT_OPTS' => "${emerge_default_opts} --usepkg --usepkg-exclude=dev-perl/*",
      'FEATURES'            => '-ipc-sandbox -pid-sandbox -network-sandbox -usersandbox',
      'MAKEOPTS'            => $makeopts,
      'PKGDIR'              => "/nest/portage/packages/${cpu}",
    }

    # Prepare the base image for OpenVox
    if $from_image =~ /gentoo/ {
      run_command('sed -i "s@^sync-uri =.*@sync-uri = rsync://rsync.us.gentoo.org/gentoo-portage/@" /usr/share/portage/config/repos.conf', $target, 'Use Gentoo US rsync mirror')
      run_command('rm -rf /var/db/repos/gentoo/.git', $target, 'Prepare Gentoo repo for rsync')
      run_command('emerge --sync', $target, 'Sync Portage tree')
    } else {
      run_command('eix-sync -aq', $target, 'Sync Portage repos')
    }

    # sys-filesystem is not an OpenVox dependency; retain it in world.
    # Match the selected interpreter for bootstrap/apply_prep, not a fixed slot.
    $ruby_target = run_command('/usr/bin/ruby -e \'puts "ruby#{RUBY_VERSION.split(".")[0, 2].join}"\'', $target, 'Find selected Ruby target').first.value['stdout'].strip
    $runtime_env = $emerge_env + { 'RUBY_TARGETS' => $ruby_target }
    if $from_image =~ /gentoo/ {
      run_command('emerge --verbose app-admin/openvox app-portage/eix dev-ruby/sys-filesystem', $target, 'Install configuration runtime', _env_vars => $runtime_env)
      # Raw Gentoo has no Nest profile yet. Bootstrap providers without world
      # roots until apply_prep installs the overlay and we select its profile.
      run_command('emerge --oneshot --verbose dev-ruby/ruby-shadow dev-ruby/ruby-augeas', $target, 'Bootstrap OpenVox providers', _env_vars => $runtime_env)
      run_command('eix-update', $target, 'Update package database')
    } else {
      run_command('emerge --verbose dev-ruby/sys-filesystem', $target, 'Retain Stage 1 filesystem library', _env_vars => $runtime_env)
    }
    run_script('nest/build/stage0-runtime.rb', $target, 'Check selected Ruby runtime', _timeout => 120)

    # Set up the build environment
    $target.apply_prep
    $target.add_facts({
      'build'               => 'stage0',
      'emerge_default_opts' => $emerge_default_opts,
      'makeopts'            => $makeopts,
      'profile'             => {},
    })

    # Run Puppet to configure Portage, distcc, and locale
    apply($target, '_description' => 'Configure Portage') {
      include nest
    }.nest::print_report

    # Rebuild the image with our profile
    run_command("eselect profile set nest:${cpu}/server", $target, 'Set profile')
    run_command('emerge --info', $target, 'Show Portage configuration')
    # A fresh Stage 0 lacks a native compiler; resolving @world directly can
    # bootstrap Rust through old slots all the way to a self-dependency.
    # Older binpkgs may have changed-deps metadata after a tree sync; limit
    # that override to this preinstall and retain USE/ABI/dependency checks.
    # The 32-bit ARM profile deliberately masks source Rust in favor of rust-bin.
    unless $cpu in ['arm1176', 'cortex-a8'] {
      $rust_command = 'emerge --oneshot --usepkgonly --binpkg-changed-deps=n --binpkg-respect-use=y dev-lang/rust'
      $rust_plan = run_command("${rust_command} --pretend --verbose --color=n", $target, 'Resolve native Rust binpkg', _env_vars => $emerge_env).first.value['stdout']
      unless $rust_plan =~ /(?m)^\s*\[binary[^\n]*\]\s+dev-lang\/rust-[0-9]/ {
        fail("No compatible native Rust binpkg resolved for ${cpu}; stop before @world")
      }
      run_command($rust_command, $target, 'Preinstall native Rust binpkg', _env_vars => $emerge_env)
    }
    if $from_image =~ /gentoo/ {
      run_command('emerge --emptytree --verbose --usepkg-exclude=dev-perl/* @world', $target, 'Rebuild all packages', _env_vars => { 'RUBY_TARGETS' => $ruby_target })
    } else {
      run_command('emerge --deep --newuse --update --verbose --with-bdeps=y --usepkg-exclude=dev-perl/* @world', $target, 'Update packages', _env_vars => { 'RUBY_TARGETS' => $ruby_target })
    }
    # Nest's OpenVox augeas/shadow USE dependencies now own these providers.
    # Deselect inherited world roots too; this does not uninstall packages.
    run_script('nest/build/stage0-runtime.rb', $target, 'Check OpenVox provider dependencies', arguments => ['--provider-dependencies'], _timeout => 120)
    run_command('emerge --deselect dev-ruby/ruby-augeas dev-ruby/ruby-shadow', $target, 'Keep OpenVox providers dependency-owned')
    run_command('emerge --depclean', $target, 'Remove unused packages')

    # Exercise the inventory interpreter, facts, native bindings and user
    # provider after cleanup, before either normal or debug image is published.
    run_script('nest/build/stage0-runtime.rb', $target, 'Check post-depclean Stage 1 runtime', arguments => ['--dependency-owned-providers', '--provider-dependencies'], _timeout => 120)

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    $image = "${registry}/nest/stage0:${cpu}"
    run_command("podman commit --change CMD=/bin/bash --squash ${container} ${image}", 'localhost', 'Commit build container')

    $debug_container = "${container}-debug"
    $debug_image = "${registry}/nest/stage0/debug:${cpu}"
    run_command("podman run --name=${debug_container} --volume=${debug_volume}:/usr/lib/.debug:ro ${qemu_args} ${image} cp -a /usr/lib/.debug/. /usr/lib/debug", 'localhost', 'Copy debug symbols')
    run_command("podman commit --change CMD=/bin/bash ${debug_container} ${debug_image}", 'localhost', 'Commit debug container')
    run_command("podman rm ${debug_container}", 'localhost', 'Remove debug container')

    unless $registry == 'localhost' {
      run_command("podman push ${image}", 'localhost', "Push ${image}")
      run_command("podman push ${debug_image}", 'localhost', "Push ${debug_image}")
    }
  }
}
