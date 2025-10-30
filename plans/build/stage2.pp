# @summary Build platform-specific images with kernels
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param platform Build for this platform
# @param variant Build this variant
# @param build Build the image
# @param cpu Build for this CPU architecture
# @param deploy Deploy the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param id Build ID
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param qemu_user_targets CPU architectures to emulate
# @param refresh Build from previous Stage 2 image
# @param registry Container registry to push to
# @param registry_username Username for registry
# @param registry_password Password for registry
# @param registry_password_var Environment variable for registry password
plan nest::build::stage2 (
  String            $container,
  String            $platform,
  String            $variant,
  Boolean           $build                 = true,
  String            $cpu                   = $platform,
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
  $target = Target.new(name => $container, uri => "podman://${container}")

  if $cpu == $platform {
    $profile = "${cpu}/${variant}"
  } else {
    $profile = "${cpu}/${platform}/${variant}"
  }

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
      $from_image = "nest/stage2/${variant}:${platform}"
    } else {
      $from_image = "nest/stage1/${variant}/debug:${cpu}"
    }

    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')

    $podman_create_cmd = @("CREATE"/L)
      podman create \
      --init \
      --name=${container} \
      --pull=always \
      --volume=/nest:/nest \
      ${qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')} \
      ${from_image} \
      sleep infinity
      | CREATE

    run_command($podman_create_cmd, 'localhost', 'Create build container')
  }

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    # Profile controls Portage and Puppet configurations
    run_command('eix-sync -aq', $target, 'Sync Portage repos')
    run_command("eselect profile set nest:${profile}", $target, 'Set profile')

    # Set up the build environment
    $target.apply_prep
    $target.add_facts({
      'build'               => 'stage2',
      'emerge_default_opts' => $emerge_default_opts,
      'makeopts'            => $makeopts,
    })

    # Run Puppet to configure Portage and set up @world
    run_command('sh -c "echo profile > /.apply_tags"', $target, 'Set Puppet tags for profile run')
    apply($target, '_description' => 'Configure the profile') { include nest }.nest::print_report
    run_command('rm /.apply_tags', $target, 'Clear Puppet tags')

    # Make the system consistent with the profile
    run_command('emerge --info', $target, 'Show Portage configuration')
    run_command('emerge --deep --exclude=sys-fs/zfs --exclude=sys-fs/zfs-kmod --newuse --update --verbose --with-bdeps=y @world', $target, 'Install packages')
    run_command('emerge --depclean', $target, 'Remove unused packages')

    # Apply the main configuration
    apply($target, '_description' => 'Configure the stage') { include nest }.nest::print_report

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    $image = "${registry}/nest/stage2/${variant}:${platform}"
    run_command("podman commit --change CMD=/bin/zsh ${container} ${image}", 'localhost', 'Commit build container')

    unless $registry == 'localhost' {
      run_command("podman push ${image}", 'localhost', "Push ${image}")
    }
  }
}
