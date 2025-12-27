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
# @param init       Include init container and disable backup job
# @param namespace  Kubernetes namespace to manage
# @param render_to  Just save the fully-rendered chart to this yaml file
# @param repo_url   Optional URL of the Helm repo to add
# @param version    Optional Helm chart version
# @param wait       Wait for resources to become available
# @param subcharts  Additional charts to deploy as part of this one
plan nest::kubernetes::deploy (
  String           $service,
  String           $app       = $service,
  Optional[String] $chart     = undef,
  Boolean          $deploy    = true,
  Boolean          $hooks     = true,
  Boolean          $init      = true,
  Optional[String] $namespace = undef,
  Optional[String] $render_to = undef,
  Optional[String] $repo_url  = undef,
  Boolean          $restore   = false,
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
    $remove_resources = []
    $remove_patches   = ['20-nest-init', '30-nest-init']
  }

  # Give extra time for any VIPs to propagate
  if $wait and !$render_to_real {
    $sleep = 10
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
