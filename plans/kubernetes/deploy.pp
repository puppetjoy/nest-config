# Install or upgrade a service
#
# Wrapper around KubeCM for Nest compatibility
#
# @param service    Installation name (what is this deployment called)
# @param app        Chart name, or your name for this deployment and set `chart_source`
# @param chart      Typically `repo_name/chart_name` or an `oci://` URI, but could be a local path,
#                     a valid Puppet file source, or `undef` for no chart (just Hiera resources).
# @param deploy     Run or skip the deployment
# @param hooks      Enable or disable install hooks
# @param init       Include init resources/containers and disable backup/restore jobs
# @param namespace  Kubernetes namespace to manage
# @param render_to  Just save the fully-rendered chart to this yaml file
# @param repo_url   Optional URL of the Helm repo to add
# @param version    Optional Helm chart version
# @param wait       Wait for resources to become available
# @param subcharts  Additional charts to deploy as part of this one
plan nest::kubernetes::deploy ( # lint:ignore:deploy_plan_boundary -- central KubeCM adapter normalizes YAML-plan inputs
  String           $service,
  String           $app       = $service,
  Optional[String] $chart     = undef,
  Boolean          $deploy    = true,
  Boolean          $hooks     = true,
  Boolean          $init      = true,
  Optional[String] $namespace = undef,
  Optional[String] $render_to = undef,
  Optional[String] $repo_url  = undef,
  Optional[String] $version   = undef,
  Boolean          $wait      = false,
  Array[Hash]      $subcharts = [],
) {
  # Handle empty string args (thanks YAML plans)
  if $render_to and $render_to != '' {
    $render_to_real = $render_to
  } else {
    $render_to_real = undef
  }

  # Initialize service and avoid conflicts with backup/restore jobs
  if $init {
    $remove_resources = ['backup', 'restore']
    $remove_patches   = []
  } else {
    $remove_resources = ['init']
    $remove_patches   = ['20-nest-init', '30-nest-init']
  }

  # Give extra time for any VIPs to propagate, claims to be satisfied, etc.
  if $wait and !$render_to_real {
    $sleep = 15
  } else {
    $sleep = undef
  }

  # Prepare subchart definitions for KubeCM
  $subcharts_modified = $subcharts.map |$subchart| {
    $subchart + {
      'release'      => $subchart['service'],
      'chart'        => $subchart['app'],
      'chart_source' => $subchart['chart'],
    } - ['service', 'app']
  }

  # Routine stack redeploys must not roll a CI-selected immutable compiler back
  # to mutable/stale Hiera and silently lose still-needed static content. Keep
  # this guard in the public adapter, not only the code-deployment caller.
  if $deploy and $app == 'openvox' and $service == 'puppet' and !$render_to_real {
    $compiler_namespace = pick_default($namespace, 'default')
    $inspect_compiler = [
      'kubectl', 'get', 'deployment', '-n', $compiler_namespace, 'puppet-puppetserver', '--ignore-not-found',
      '-o', 'jsonpath={.spec.template.spec.containers[0].volumeMounts[?(@.name=="compiler-snapshots")].name}',
    ].shellquote
    $compiler_mode = run_command($inspect_compiler, 'localhost', 'Inspect existing OpenVox compiler before stack deployment').first.value['stdout'].strip
    if $compiler_mode != '' {
      $guard_directory = run_command(
        'umask 077; mkdir -p rollout-evidence && mktemp -d rollout-evidence/compiler-chart.XXXXXXXX',
        'localhost', 'Create private compiler chart preflight directory',
      ).first.value['stdout'].strip
      $guard_manifest = "${guard_directory}/rendered.yaml"
      run_plan('nest::kubernetes::deploy', {
        service => $service, app => $app, chart => $chart, deploy => $deploy,
        hooks => $hooks, init => $init, namespace => $namespace, render_to => $guard_manifest,
        repo_url => $repo_url, version => $version, wait => false, subcharts => $subcharts,
      })
      $guard_command = ['python3', 'scripts/nest-compiler-rollout.py', '--guard-chart', $compiler_namespace, $guard_manifest].shellquote
      run_command($guard_command, 'localhost', 'Refuse loss of retained compiler identities')
    }
  }

  return run_plan('kubecm::deploy', {
    release          => $service,
    chart            => $app,
    chart_source     => $chart,
    deploy           => $deploy,
    hooks            => $hooks,
    namespace        => $namespace,
    remove_resources => $remove_resources,
    remove_patches   => $remove_patches,
    render_to        => $render_to_real,
    repo_url         => $repo_url,
    version          => $version,
    wait             => $wait,
    sleep            => $sleep,
    subcharts        => $subcharts_modified,
  })
}
