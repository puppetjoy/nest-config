# @summary Simple package builder for the Chromium web browser
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param cpu Build for this CPU
# @param build Build the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param qemu_user_targets CPU architectures to emulate
plan nest::build::chromium (
  String            $container,
  String            $cpu,
  String            $version,
  Boolean           $build               = true,
  Optional[String]  $emerge_default_opts = undef,
  Boolean           $init                = true,
  Optional[String]  $makeopts            = undef,
  Array[String]     $qemu_user_targets   = lookup('nest::build::qemu_user_targets', default_value => []),
) {
  $build_volume = "${container}-build"
  $repos_volume = "${container}-repos"
  $target = Target.new(name => $container, uri => "podman://${container}")

  if $init {
    run_command("podman rm -f ${container}", 'localhost', 'Stop and remove existing build container')

    $podman_create_cmd = @("CREATE"/L)
      podman create \
      --init \
      --name=${container} \
      --pull=always \
      --volume=/nest:/nest \
      ${qemu_user_targets.map |$arch| { "--volume=/usr/bin/qemu-${arch}:/usr/bin/qemu-${arch}:ro" }.join(' ')} \
      --volume=${build_volume}:/var/tmp/portage \
      --volume=${repos_volume}:/var/db/repos \
      nest/stage1/workstation:${cpu} \
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
      'build'               => 'chromium',
      'emerge_default_opts' => $emerge_default_opts,
      'makeopts'            => $makeopts,
    })

    # Run Puppet to configure Portage
    run_command('sh -c "echo profile > /.apply_tags"', $target, 'Set Puppet tags for profile run')
    apply($target, '_description' => 'Configure the profile') { include nest }.nest::print_report
    run_command('rm /.apply_tags', $target, 'Clear Puppet tags')

    # Build Chromium with Portage
    run_command('emerge --info', $target, 'Show Portage configuration')
    run_command("emerge --onlydeps --verbose --with-bdeps=y '=www-client/chromium-${version}'", $target, 'Install dependencies')
    run_command("sh -c 'ebuild /var/db/repos/gentoo/www-client/chromium/chromium-${version}.ebuild package > /dev/null'", $target,  'Build Chromium')

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }
}
