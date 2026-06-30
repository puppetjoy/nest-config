# @summary Build Camofox Browser tool image
#
# Use bin/build script to run this plan.
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
plan nest::build::camofox (
  String            $container,
  String            $cpu                   = 'zen5',
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

  run_plan('nest::build::tool', {
    container           => $container,
    cpu                 => $cpu,
    tool                => 'camofox',
    tag                 => 'latest',
    build               => $build,
    deploy              => false,
    emerge_default_opts => $emerge_default_opts,
    id                  => $id,
    init                => $init,
    makeopts            => $makeopts,
    qemu_user_targets   => $qemu_user_targets,
    refresh             => $refresh,
    image_changes       => [
      'CMD=/usr/local/bin/nest-camofox-browser',
      'WORKDIR=/home/node',
    ],
  })

  if $build {
    run_command("podman start ${container}", 'localhost', 'Start build container')
    run_command("podman exec ${container} /bin/sh -lc 'command -v camofox-browser && timeout 20s nest-camofox-browser >/tmp/nest-camofox-smoke.log 2>&1; status=\$?; cat /tmp/nest-camofox-smoke.log; test \"\$status\" -eq 124 && ! /bin/grep -E \"CannotFindXvfb|Couldn.t load XPCOM|unhandledRejection|cannot open shared object file\" /tmp/nest-camofox-smoke.log'", 'localhost', 'Smoke test Camofox Browser startup')
    run_command("podman stop ${container}", 'localhost', 'Stop build container')
  }

  if $deploy {
    run_plan('nest::build::tool', {
      container             => $container,
      cpu                   => $cpu,
      tool                  => 'camofox',
      tag                   => 'latest',
      build                 => false,
      deploy                => true,
      init                  => false,
      registry              => $registry,
      registry_username     => $registry_username,
      registry_password     => $registry_password,
      registry_password_var => $registry_password_var,
      image_changes         => [
        'CMD=/usr/local/bin/nest-camofox-browser',
        'WORKDIR=/home/node',
      ],
    })
  }
}
