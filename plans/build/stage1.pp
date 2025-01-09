# @summary Build basic images intended for containers
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param cpu Build for this CPU architecture
# @param variant Build for this Nest variant
# @param build Build the image
# @param deploy Deploy the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param id Build ID
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param qemu_user_targets CPU architectures to emulate
# @param refresh Build from previous Stage 1 image
# @param registry Container registry to push to
# @param registry_username Username for registry
# @param registry_password Password for registry
# @param registry_password_var Environment variable for registry password
plan nest::build::stage1 (
  String            $container,
  String            $cpu,
  String            $variant,
  Boolean           $build                 = true,
  Boolean           $deploy                = false,
  Optional[String]  $emerge_default_opts   = undef,
  Optional[Numeric] $id                    = undef,
  Boolean           $init                  = true,
  Optional[String]  $makeopts              = undef,
  Array[String]     $qemu_user_targets     = lookup('nest::build::qemu_user_targets', default_value => []),
  Boolean           $refresh               = false,
  String            $registry              = lookup('nest::build::registry', default_value => 'localhost'),
  Optional[String]  $registry_username     = lookup('nest::build::registry_username', default_value => undef),
  Optional[String]  $registry_password     = lookup('nest::build::registry_password', default_value => undef),
  String            $registry_password_var = 'NEST_REGISTRY_PASSWORD',
) {
  $debug_volume = "${container}-debug"
  $repos_volume = "${container}-repos" # cached between builds
  $target = Target.new(name => $container, uri => "podman://${container}")

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
    if $refresh {
      $from_image       = "nest/stage1/${variant}:${cpu}"
      $from_image_debug = "nest/stage1/${variant}/debug:${cpu}"
    } else {
      $from_image       = "nest/stage0:${cpu}"
      $from_image_debug = "nest/stage0/debug:${cpu}"
    }

    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')
    run_command("podman volume rm -f ${debug_volume}", 'localhost', 'Remove existing debug volume')

    $podman_debug_copy_cmd = @("COPY"/L)
      podman run \
      --name=${container} \
      --pull=always \
      --rm \
      --volume=${debug_volume}:/usr/lib/.debug \
      ${from_image_debug} \
      cp -a /usr/lib/debug/. /usr/lib/.debug
      | COPY

    run_command($podman_debug_copy_cmd, 'localhost', 'Repopulate debug volume')

    $podman_create_cmd = @("CREATE"/L)
      podman create \
      --name=${container} \
      --pull=always \
      --stop-signal=SIGKILL \
      --volume=/nest:/nest \
      ${qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')} \
      --volume=${debug_volume}:/usr/lib/debug \
      --volume=${repos_volume}:/var/db/repos \
      ${from_image} \
      sleep infinity
      | CREATE

    run_command($podman_create_cmd, 'localhost', 'Create build container')
  }

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    # Profile controls Portage and Puppet configurations
    run_command('eix-sync -aq', $target, 'Sync Portage repos')
    run_command("eselect profile set nest:${cpu}/${variant}", $target, 'Set profile')

    # Set up the build environment
    $target.apply_prep
    $target.add_facts({
      'build'               => 'stage1',
      'emerge_default_opts' => $emerge_default_opts,
      'makeopts'            => $makeopts,
    })

    # Run Puppet to configure Portage and set up @world
    run_command('sh -c "echo profile > /.apply_tags"', $target, 'Set Puppet tags for profile run')
    apply($target, '_description' => 'Configure the profile') { include nest }.nest::print_report
    run_command('rm /.apply_tags', $target, 'Clear Puppet tags')
    run_command('emerge --info', $target, 'Show Portage configuration')

    # Resolve circular dependencies
    if $variant == 'workstation' and !$refresh {
      run_command('emerge --oneshot --verbose media-libs/harfbuzz media-libs/freetype media-libs/mesa', $target, 'Resolve media circular dependencies', _env_vars => {
        'USE' => '-cairo -harfbuzz -truetype -vaapi',
      })
      run_command('emerge --oneshot --verbose x11-misc/xdg-utils', $target, 'Resolve Plasma circular dependencies', _env_vars => {
        'USE' => '-plasma',
      })
    }

    # Make the system consistent with the profile
    run_command('emerge --deep --newuse --update --verbose --with-bdeps=y @world', $target, 'Install packages')
    run_command('emerge --depclean', $target, 'Remove unused packages')

    # Apply the main configuration
    apply($target, '_description' => 'Configure the stage') { include nest }.nest::print_report

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    $image = "${registry}/nest/stage1/${variant}:${cpu}"
    run_command("podman commit --change CMD=/bin/zsh ${container} ${image}", 'localhost', 'Commit build container')

    $debug_container = "${container}-debug"
    $debug_image = "${registry}/nest/stage1/${variant}/debug:${cpu}"
    run_command("podman run --name=${debug_container} --volume=${debug_volume}:/usr/lib/.debug:ro ${image} cp -a /usr/lib/.debug/. /usr/lib/debug", 'localhost', 'Copy debug symbols')
    run_command("podman commit --change CMD=/bin/zsh ${debug_container} ${debug_image}", 'localhost', 'Commit debug container')
    run_command("podman rm ${debug_container}", 'localhost', 'Remove debug container')

    unless $registry == 'localhost' {
      run_command("podman push ${image}", 'localhost', "Push ${image}")
      run_command("podman push ${debug_image}", 'localhost', "Push ${debug_image}")
    }
  }
}
