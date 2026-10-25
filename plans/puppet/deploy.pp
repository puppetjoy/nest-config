# Deploy the Puppet control repo to test and production OpenVox
plan nest::puppet::deploy ( # lint:ignore:deploy_plan_boundary -- code rollout plan, not Kubernetes stack initialization
  Enum['test', 'prod', 'kubernetes', 'both', 'all'] $backend            = 'kubernetes',
  Optional[String[1]]                               $environment        = 'main',
  Boolean                                           $all_environments   = false,
  Optional[String[1]]                               $compiler_candidate = undef,
  String[1]                                         $compiler_output    = 'rollout-evidence/compiler',
) {
  $environment_args = $all_environments ? {
    true    => [],
    default => [$environment],
  }

  if (!$all_environments) and ($environment !~ String[1]) {
    fail('environment must be set unless all_environments=true')
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

  # Keep both/all as compatibility aliases for test + prod, never Podman.
  $selected_openvox_backends = $backend ? {
    'test'       => ['test'],
    'prod'       => ['prod'],
    'kubernetes' => ['test', 'prod'],
    'both'       => ['test', 'prod'],
    'all'        => ['test', 'prod'],
    default      => [],
  }

  # Do not update r10k and report success while an immutable compiler continues
  # serving its prior selected snapshot. Preflight every backend before writes.
  $selected_openvox_backends.each |$openvox_backend| {
    $namespace = $openvox_backends[$openvox_backend]['namespace']
    $inspect_cmd = [
      'kubectl', 'get', 'deployment', '-n', $namespace, 'puppet-puppetserver',
      '-o', 'jsonpath={.spec.template.spec.containers[0].volumeMounts[?(@.name=="compiler-snapshots")].name}',
    ].shellquote
    $frozen = run_command($inspect_cmd, 'localhost', 'Inspect compiler deployment mode').first.value['stdout'].strip
    if $frozen != '' {
      if !$compiler_candidate or $all_environments or $environment != 'main' {
        fail('Immutable compiler selected: supply its exact main compiler_candidate; mutable r10k deployment refused')
      }
      $preflight_cmd = [
        'python3', 'scripts/nest-compiler-rollout.py', $compiler_candidate, $namespace,
        "${compiler_output}/${namespace}", '--check',
      ].shellquote
      run_command($preflight_cmd, 'localhost', 'Preflight additive immutable compiler selection')
    }
  }

  $selected_openvox_backends.each |$openvox_backend| {
    $openvox     = $openvox_backends[$openvox_backend]
    $namespace   = $openvox['namespace']
    $description = $openvox['description']
    $deployment  = 'deploy/puppet-puppetserver'

    # Reinspect before choosing a writer: a concurrent mode change must not
    # make the old mutable writer refresh a frozen compiler silently.
    $mode_cmd = [
      'kubectl', 'get', 'deployment', '-n', $namespace, 'puppet-puppetserver',
      '-o', 'jsonpath={.spec.template.spec.containers[0].volumeMounts[?(@.name=="compiler-snapshots")].name}',
    ].shellquote
    $mode = run_command($mode_cmd, 'localhost', 'Reinspect compiler deployment mode').first.value['stdout'].strip
    if $mode != '' {
      if !$compiler_candidate or $all_environments or $environment != 'main' {
        fail('Compiler mode changed; mutable r10k deployment refused')
      }
      $rollout_cmd = [
        'python3', 'scripts/nest-compiler-rollout.py', $compiler_candidate, $namespace,
        "${compiler_output}/${namespace}", '--deploy',
      ].shellquote
      run_command($rollout_cmd, 'localhost', "Roll out accepted immutable compiler to ${description}")
      next()
    }

    $wait_cmd = [
      'kubectl', 'wait', '-n', $namespace,
      '--for=jsonpath={.status.containerStatuses[?(@.name=="r10k-code")].ready}=true',
      'pod', '-l', 'app.kubernetes.io/component=puppetserver',
      '--timeout=180s',
    ].shellquote

    $deploy_cmd = ([
      'kubectl', 'exec', '-n', $namespace, $deployment,
      '-c', 'r10k-code', '--',
      '/container-entrypoint.sh', 'deploy', 'environment',
    ] + $environment_args + [
      '--config', '/etc/puppetlabs/puppet/r10k_code.yaml',
      '--puppetfile',
    ]).shellquote

    run_command($wait_cmd, 'localhost', "Wait for ${description} r10k sidecar")
    run_command($deploy_cmd, 'localhost', "Deploy Puppet code to ${description}")

    # r10k updates the files, not the JRuby compiler's loaded environment.
    # Explicitly expire it before a catalog can mix old classes/new templates.
    $cache_url_suffix = $all_environments ? {
      true    => '',
      default => "?environment=${environment}",
    }
    $expire_script = @(SCRIPT)
      set -eu
      certname=$(puppet config print certname --section server)
      curl --fail --silent --show-error --request DELETE \
        --cert "/etc/puppetlabs/puppet/ssl/certs/$certname.pem" \
        --key "/etc/puppetlabs/puppet/ssl/private_keys/$certname.pem" \
        --cacert /etc/puppetlabs/puppet/ssl/certs/ca.pem \
        "https://$certname:8140/puppet-admin-api/v1/environment-cache$1"
      | SCRIPT
    $expire_cmd = [
      'kubectl', 'exec', '-n', $namespace, $deployment,
      '-c', 'puppet-puppetserver', '--', '/bin/sh', '-ec', $expire_script, '--', $cache_url_suffix,
    ].shellquote

    run_command($expire_cmd, 'localhost', "Expire ${description} compiler environment cache")

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
