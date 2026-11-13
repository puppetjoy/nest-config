# Joyride credentials are supplied by the private Hiera repository. Application
# pods receive only their environment's runtime Secret; database credentials are
# generated separately by CloudNativePG. Never place tokens in public app data.
class nest::service::joyride (
  Optional[Sensitive[Hash[String, String]]] $runtime_secrets                  = undef,
  Optional[Sensitive[String]]               $registry_dockerconfig            = undef,
  Optional[Sensitive[String]]               $artifact_verifier_token          = undef,
  Optional[Sensitive[String]]               $test_smtp_password               = undef,
  Optional[Sensitive[Hash[String, String]]] $production_runtime_secrets       = undef,
  Optional[Sensitive[String]]               $production_registry_dockerconfig = undef,
  Optional[Sensitive[String]]               $production_stripe_secret_key     = undef,
  Optional[Sensitive[String]]               $production_stripe_webhook_secret = undef,
  Optional[Sensitive[String]]               $production_smtp_password         = undef,
) {
  $runtime_environment = lookup('runtime_environment', { 'default_value' => undef })
  $is_test = $nest::kubernetes::namespace == 'test' and $nest::kubernetes::service == 'joyride-test' and $runtime_environment == 'test'
  $is_production = $nest::kubernetes::namespace == 'joyride' and $nest::kubernetes::service == 'joyride' and $runtime_environment == 'production'
  if !$is_test and !$is_production {
    fail('Joyride supports only joyride-test/test/test or joyride/joyride/production')
  }

  if $is_test {
    # Reject an unsupported environment before asking for credentials. Optional
    # parameters permit that ordering, not a credential-free TEST deployment.
    if $runtime_secrets == undef or $registry_dockerconfig == undef or $artifact_verifier_token == undef {
      fail('Joyride TEST requires managed runtime, registry and read-only artifact-verifier credentials')
    }

    # Dedicated TEST credential only; never fall back to the shared account map.
    if $test_smtp_password == undef {
      fail('Joyride TEST requires its dedicated managed TEST SMTP credential')
    }
    if $test_smtp_password.unwrap == '' {
      fail('Joyride TEST refuses an empty dedicated SMTP credential')
    }

    $django_secret_key_base64      = base64('encode', $runtime_secrets.unwrap['DJANGO_SECRET_KEY']).chomp
    $ops_token_base64              = base64('encode', $runtime_secrets.unwrap['OPS_TOKEN']).chomp
    $delivery_token_base64         = base64('encode', $runtime_secrets.unwrap['DELIVERY_TOKEN']).chomp
    $wmata_api_key_base64          = base64('encode', $runtime_secrets.unwrap['WMATA_API_KEY']).chomp
    $email_host_password_base64    = base64('encode', $test_smtp_password.unwrap).chomp
    # Optional while billing is disabled. Never admit live credentials to TEST.
    $stripe_keys = {
      'STRIPE_SECRET_KEY'      => '',
      'STRIPE_PUBLISHABLE_KEY' => '',
      'STRIPE_WEBHOOK_SECRET'  => '',
    } + $runtime_secrets.unwrap
    $stripe_secret_key             = $stripe_keys['STRIPE_SECRET_KEY']
    $stripe_publishable_key        = $stripe_keys['STRIPE_PUBLISHABLE_KEY']
    $stripe_webhook_secret         = $stripe_keys['STRIPE_WEBHOOK_SECRET']
    if $stripe_secret_key != '' and $stripe_secret_key !~ /^sk_test_/ {
      fail('Joyride TEST refuses non-sandbox Stripe secret keys')
    }
    if $stripe_publishable_key != '' and $stripe_publishable_key !~ /^pk_test_/ {
      fail('Joyride TEST refuses non-sandbox Stripe publishable keys')
    }
    $stripe_secret_key_base64      = base64('encode', $stripe_secret_key).chomp
    $stripe_publishable_key_base64 = base64('encode', $stripe_publishable_key).chomp
    $stripe_webhook_secret_base64  = base64('encode', $stripe_webhook_secret).chomp
    $registry_dockerconfig_base64  = base64('encode', $registry_dockerconfig.unwrap).chomp
    $verifier_token_base64         = base64('encode', $artifact_verifier_token.unwrap).chomp
    $artifact_import_base64        = base64('encode', file('nest/app/joyride/import_artifacts.py'))
    $test_delivery_base64          = base64('encode', file('nest/app/joyride/test_delivery_controller.py'))
    $bootstrap_gate_base64         = base64('encode', file('nest/app/joyride/bootstrap_gate.py'))
    $bootstrap_gate_sha256         = sha256(file('nest/app/joyride/bootstrap_gate.py'))
    $routing_installer_base64      = base64('encode', file('nest/app/joyride/install_routing_graph.py'))
    $routing_installer_sha256      = sha256(file('nest/app/joyride/install_routing_graph.py'))
    $routing_cache_base64          = base64('encode', file('nest/app/joyride/cache_routing_graph.py'))
    $routing_cache_sha256          = sha256(file('nest/app/joyride/cache_routing_graph.py'))
    $test_access_config_base64     = base64('encode', file('nest/app/joyride/test-access-nginx.conf'))
    $test_access_config_sha256     = sha256(file('nest/app/joyride/test-access-nginx.conf'))
    $production_ops_config_base64  = base64('encode', file('nest/app/joyride/production-ops-nginx.conf'))
    $production_ops_config_sha256  = sha256(file('nest/app/joyride/production-ops-nginx.conf'))
  } else {
    if $production_runtime_secrets == undef or $production_registry_dockerconfig == undef or $production_stripe_secret_key == undef or $production_stripe_webhook_secret == undef or $production_smtp_password == undef {
      fail('Joyride production requires managed runtime, registry, Stripe and SMTP credentials')
    }
    $prod_runtime = $production_runtime_secrets.unwrap
    if $prod_runtime.keys.sort != ['DJANGO_SECRET_KEY', 'OPS_TOKEN', 'WMATA_API_KEY'] {
      fail('Joyride production runtime secrets must contain exactly DJANGO_SECRET_KEY, OPS_TOKEN and WMATA_API_KEY')
    }
    if $prod_runtime['DJANGO_SECRET_KEY'] == undef or $prod_runtime['DJANGO_SECRET_KEY'] == '' or $prod_runtime['OPS_TOKEN'] == undef or $prod_runtime['OPS_TOKEN'] == '' or $prod_runtime['WMATA_API_KEY'] == undef or $prod_runtime['WMATA_API_KEY'] == '' {
      fail('Joyride production requires nonempty DJANGO_SECRET_KEY, OPS_TOKEN and WMATA_API_KEY')
    }
    if $production_stripe_secret_key.unwrap !~ /^(rk_live_|sk_live_)/ or $production_stripe_webhook_secret.unwrap !~ /^whsec_/ {
      fail('Joyride production requires live Stripe secret and webhook credentials')
    }
    if $production_smtp_password.unwrap == '' or $production_registry_dockerconfig.unwrap == '' {
      fail('Joyride production refuses empty SMTP or registry credentials')
    }
    $production_django_secret_key_base64 = base64('encode', $prod_runtime['DJANGO_SECRET_KEY']).chomp
    $production_ops_token_base64 = base64('encode', $prod_runtime['OPS_TOKEN']).chomp
    $production_wmata_api_key_base64 = base64('encode', $prod_runtime['WMATA_API_KEY']).chomp
    $production_smtp_password_base64 = base64('encode', $production_smtp_password.unwrap).chomp
    $production_stripe_secret_key_base64 = base64('encode', $production_stripe_secret_key.unwrap).chomp
    $production_stripe_webhook_secret_base64 = base64('encode', $production_stripe_webhook_secret.unwrap).chomp
    $production_registry_dockerconfig_base64 = base64('encode', $production_registry_dockerconfig.unwrap).chomp
    $production_ops_config_base64 = base64('encode', file('nest/app/joyride/production-ops-nginx.conf'))
    $production_ops_config_sha256 = sha256(file('nest/app/joyride/production-ops-nginx.conf'))
    $production_access_config_base64 = base64('encode', file('nest/app/joyride/production-access-nginx.conf'))
    $production_access_config_sha256 = sha256(file('nest/app/joyride/production-access-nginx.conf'))
    $production_routing_installer_base64 = base64('encode', file('nest/app/joyride/install_routing_graph.py'))
    $production_routing_installer_sha256 = sha256(file('nest/app/joyride/install_routing_graph.py'))
  }
}
