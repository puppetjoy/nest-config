# @summary Build a standard tool image
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param cpu Build for this CPU architecture
# @param tool Build this tool
# @param build Build the image
# @param deploy Deploy the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param id Build ID
# @param image_changes Additional image instruction (e.g. ENV=NAME=val,WORKDIR=/path)
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param qemu_user_targets CPU architectures to emulate
# @param refresh Build from previous tool image
# @param registry Container registry to push to
# @param registry_username Username for registry
# @param registry_password Password for registry
# @param registry_password_var Environment variable for registry password
plan nest::build::tool (
  String            $container,
  String            $cpu,
  String            $tool,
  Boolean           $build                 = true,
  Boolean           $deploy                = false,
  Optional[String]  $emerge_default_opts   = undef,
  Optional[Numeric] $id                    = undef,
  Array[String]     $image_changes         = [],
  Boolean           $init                  = true,
  Optional[String]  $makeopts              = undef,
  Array[String]     $qemu_user_targets     = lookup('nest::build::qemu_user_targets', default_value => []),
  Boolean           $refresh               = false,
  String            $registry              = lookup('nest::build::registry', default_value => 'localhost'),
  Optional[String]  $registry_username     = lookup('nest::build::registry_username', default_value => undef),
  Optional[String]  $registry_password     = lookup('nest::build::registry_password', default_value => undef),
  String            $registry_password_var = 'NEST_REGISTRY_PASSWORD',
) {
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
      $from_image = "nest/tool/${tool}:${cpu}"
    } else {
      $from_image = "nest/stage1/server:${cpu}"
    }

    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')

    $podman_create_cmd = @("CREATE"/L)
      podman create \
      --init \
      --name=${container} \
      --pull=always \
      --volume=/nest:/nest \
      ${qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')} \
      --volume=${repos_volume}:/var/db/repos \
      ${from_image} \
      sleep infinity
      | CREATE

    run_command($podman_create_cmd, 'localhost', 'Create build container')
  }

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    run_command('eix-sync -aq', $target, 'Sync Portage repos')

    # Set up the build environment
    $target.apply_prep
    $target.add_facts({
      'build'               => $tool,
      'emerge_default_opts' => $emerge_default_opts,
      'makeopts'            => $makeopts,
    })

    # Apply the configuration
    apply($target, '_description' => 'Configure the tool') { include nest }.nest::print_report

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    $commit_changes = (['CMD=/bin/zsh'] + $image_changes).map |$change| { "--change ${change.shellquote}" }.join(' ')
    $image = "${registry}/nest/tools/${tool}:${cpu}"
    run_command("podman commit ${commit_changes} ${container} ${image}", 'localhost', 'Commit build container')

    unless $registry == 'localhost' {
      run_command("podman push ${image}", 'localhost', "Push ${image}")
    }
  }
}
