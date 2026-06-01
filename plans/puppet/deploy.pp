# Deploy the Puppet control repo into the Kubernetes OpenVox service
plan nest::puppet::deploy () {
  $namespace   = 'default'
  $deployment  = 'deploy/puppet-puppetserver-puppetserver-master'
  $environment = 'main'

  $deploy_cmd = [
    'kubectl', 'exec', '-n', $namespace, $deployment,
    '-c', 'r10k-code', '--',
    '/container-entrypoint.sh', 'deploy', 'environment', $environment,
    '--config', '/etc/puppetlabs/puppet/r10k_code.yaml',
    '--puppetfile',
  ].shellquote

  run_command($deploy_cmd, 'localhost', 'Deploy Puppet code')

  $verify_cmd = [
    'kubectl', 'exec', '-n', $namespace, $deployment,
    '-c', 'r10k-code', '--',
    'git', '-C', "/etc/puppetlabs/code/environments/${environment}",
    'rev-parse', '--short', 'HEAD',
  ].shellquote

  run_command($verify_cmd, 'localhost', 'Verify Puppet code deployment')
}
