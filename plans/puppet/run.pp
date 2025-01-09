# Initiate and wait for a Puppet run
#
# @param targets A list of targets to run Puppet on
# @param build Toggle additional build functionality in the Puppet run
# @param environment The Puppet environment to use
# @param noop Run Puppet in noop mode
# @param skip_module_rebuild Skip kernel module rebuild
# @param tags Only apply resources with these tags
plan nest::puppet::run (
  TargetSpec $targets,
  Optional[Enum['kernel']] $build               = undef,
  Optional[String]         $environment         = undef,
  Boolean                  $noop                = false,
  Boolean                  $skip_module_rebuild = false,
  Array[String]            $tags                = [],
) {
  if $build {
    $build_env = { 'FACTER_build' => $build }
  } else {
    $build_env = {}
  }

  if $skip_module_rebuild {
    $skip_env = { 'FACTER_skip_module_rebuild' => 1 }
  } else {
    $skip_env = {}
  }

  if !empty($environment) {
    $environment_args = ['--environment', $environment]
  } else {
    $environment_args = []
  }

  if $noop {
    $noop_args = ['--noop']
  } else {
    $noop_args = []
  }

  if !empty($tags) {
    $tags_args = ['--tags', $tags.join(',')]
  } else {
    $tags_args = []
  }

  run_script('nest/scripts/run_puppet.sh', $targets, 'Run Puppet', {
    _env_vars => $build_env + $skip_env + {
      'PUPPET_EXTRA_ARGS' => shellquote($environment_args + $noop_args + $tags_args),
    },
    _run_as   => 'root',
  })
}
