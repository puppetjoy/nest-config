class nest::kubernetes {
  $service        = $kubecm::deploy::release
  $app            = $kubecm::deploy::chart
  $namespace      = $kubecm::deploy::namespace
  $parent_service = $kubecm::deploy::parent

  # For resources deployments, derive main service name
  # (e.g., gitlab-resources -> gitlab)
  $main_service = $service.regsubst('-resources$', '')

  # Different from service--the user-facing name
  # (e.g., service = gitlab, service_name = gitlab-test)
  $service_name = lookup('service_name', default_value => $service)

  if $service_name {
    $cron_job_offset  = stdlib::seeded_rand(60, $service_name)
    $fqdn             = "${service_name}.eyrie"
    $load_balancer_ip = lookup('nest::host_records')[$fqdn]
  } else {
    $cron_job_offset  = 0
    $fqdn             = undef
    $load_balancer_ip = undef
  }

  $registry_auths = stdlib::to_json({
    'auths' => lookup('nest::registry_tokens').reduce({}) |$result, $token| {
      $result + { $token[0] => { 'auth' => base64('encode', $token[1]).chomp } }
    },
  })
  $registry_auths_base64 = base64('encode', $registry_auths)
}
