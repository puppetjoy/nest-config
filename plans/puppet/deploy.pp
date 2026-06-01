# Deploy the Puppet control repo during the OpenVox migration
# nest-lint: allow-deploy-pp-plan - code rollout plan, not Kubernetes stack initialization
plan nest::puppet::deploy (
  Enum['legacy', 'test', 'prod', 'kubernetes', 'both', 'all'] $backend     = 'all',
  Optional[String[1]]                                         $environment = undef,
) {
  $environment_args = $environment ? {
    undef   => [],
    default => [$environment],
  }

  if $backend in ['legacy', 'both', 'all'] {
    $legacy_cmd = (['/srv/puppet/bin/r10k', 'deploy', 'environment'] + $environment_args + ['-pv']).shellquote

    run_command($legacy_cmd, 'puppet-server', 'Deploy Puppet code to legacy puppet-server', '_run_as' => 'root')
  }

  $openvox_backends = {
    'test' => {
      namespace   => 'test',
      description => 'test OpenVox',
    },
    'prod' => {
      namespace   => 'default',
      description => 'prod OpenVox',
    },
  }

  $selected_openvox_backends = $backend ? {
    'test'       => ['test'],
    'prod'       => ['prod'],
    'kubernetes' => ['test', 'prod'],
    'both'       => ['test', 'prod'],
    'all'        => ['test', 'prod'],
    default      => [],
  }

  $selected_openvox_backends.each |$openvox_backend| {
    $openvox     = $openvox_backends[$openvox_backend]
    $namespace   = $openvox['namespace']
    $description = $openvox['description']
    $deployment  = 'deploy/puppet-puppetserver'

    $deploy_cmd = ([
      'kubectl', 'exec', '-n', $namespace, $deployment,
      '-c', 'r10k-code', '--',
      '/container-entrypoint.sh', 'deploy', 'environment',
    ] + $environment_args + [
      '--config', '/etc/puppetlabs/puppet/r10k_code.yaml',
      '--puppetfile',
    ]).shellquote

    run_command($deploy_cmd, 'localhost', "Deploy Puppet code to ${description}")

    if $environment =~ String[1] {
      $verify_cmd = [
        'kubectl', 'exec', '-n', $namespace, $deployment,
        '-c', 'r10k-code', '--',
        'git', '-C', "/etc/puppetlabs/code/environments/${environment}",
        'rev-parse', '--short', 'HEAD',
      ].shellquote
    } else {
      $verify_cmd = [
        'kubectl', 'exec', '-n', $namespace, $deployment,
        '-c', 'r10k-code', '--',
        '/bin/sh', '-c',
        'for env in /etc/puppetlabs/code/environments/*; do [ -d "$env" ] && basename "$env"; done | sort',
      ].shellquote
    }

    run_command($verify_cmd, 'localhost', "Verify ${description} Puppet code deployment")
  }
}
