# @summary Build Puppet Development Kit
#
# Use bin/build script to run this plan!
#
# @param container Build container name
# @param cpu Build for this CPU architecture
# @param build Build the image
# @param deploy Deploy the image
# @param emerge_default_opts Override default emerge options (e.g. --jobs=4)
# @param id Build ID
# @param init Initialize the build container
# @param makeopts Override make flags (e.g. -j4)
# @param qemu_user_targets CPU architectures to emulate
# @param refresh Build from previous tool image
# @param registry Container registry to push to
# @param registry_username Username for registry
# @param registry_password Password for registry
# @param registry_password_var Environment variable for registry password
plan nest::build::pdk (
  String            $container,
  String            $cpu,
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
  $target = Target.new(name => $container, uri => "podman://${container}")

  $puppetcore_gem_source = system::env('GEM_SOURCE_PUPPETCORE')
  $puppet_forge_token    = system::env('PUPPET_FORGE_TOKEN')
  $puppetcore_env_vars   = {
    'BUNDLE_RUBYGEMS___PUPPETCORE__PUPPET__COM' => "forge-key:${puppet_forge_token}",
    'GEM_SOURCE_PUPPETCORE'                     => $puppetcore_gem_source,
    'PUPPET_FORGE_TOKEN'                        => $puppet_forge_token,
  }

  run_plan('nest::build::tool', {
    container             => $container,
    cpu                   => $cpu,
    tool                  => 'pdk',
    build                 => $build,
    deploy                => false,
    emerge_default_opts   => $emerge_default_opts,
    extra_volumes         => ['/etc/gemrc:/etc/gemrc:ro'],
    id                    => $id,
    init                  => $init,
    makeopts              => $makeopts,
    qemu_user_targets     => $qemu_user_targets,
    refresh               => $refresh,
  })

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')

    run_command('pdk new module --skip-interview build /module', $target, 'Create test module', _env_vars => $puppetcore_env_vars)
    run_command('sh -c "cd /module && bundle install && pdk validate"', $target, 'Install gems and validate module', _env_vars => $puppetcore_env_vars)
    run_command('rm -rf /module && mkdir /module', $target, 'Clean up test module')

    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    run_plan('nest::build::tool', {
      container             => $container,
      cpu                   => $cpu,
      tool                  => 'pdk',
      build                 => false,
      deploy                => true,
      image_changes         => ['ENV=PDK_DISABLE_ANALYTICS=true', 'WORKDIR=/module'],
      init                  => false,
      registry              => $registry,
      registry_username     => $registry_username,
      registry_password     => $registry_password,
      registry_password_var => $registry_password_var,
    })
  }
}
