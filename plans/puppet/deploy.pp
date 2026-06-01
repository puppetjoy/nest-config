# Deploy the Puppet control repo during the OpenVox migration
plan nest::puppet::deploy (
  Enum['legacy', 'test', 'both'] $backend = 'both',
  Optional[String[1]]             $environment = undef,
) {
  $environment_args = $environment ? {
    undef   => [],
    default => [$environment],
  }

  if $backend in ['legacy', 'both'] {
    $legacy_cmd = (['/srv/puppet/bin/r10k', 'deploy', 'environment'] + $environment_args + ['-pv']).shellquote

    run_command($legacy_cmd, 'puppet-server', 'Deploy Puppet code to legacy puppet-server', '_run_as' => 'root')
  }

  if $backend in ['test', 'both'] {
    $namespace  = 'test'
    $deployment = 'deploy/puppet-puppetserver-puppetserver-master'

    $deploy_cmd = ([
      'kubectl', 'exec', '-n', $namespace, $deployment,
      '-c', 'r10k-code', '--',
      '/container-entrypoint.sh', 'deploy', 'environment',
    ] + $environment_args + [
      '--config', '/etc/puppetlabs/puppet/r10k_code.yaml',
      '--puppetfile',
    ]).shellquote

    run_command($deploy_cmd, 'localhost', 'Deploy Puppet code to test OpenVox')

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

    run_command($verify_cmd, 'localhost', 'Verify test OpenVox Puppet code deployment')
  }
}
