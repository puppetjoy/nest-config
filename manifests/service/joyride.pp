# Joyride credentials are supplied by the private Hiera repository. Application
# pods receive only their environment's runtime Secret; database credentials are
# generated separately by CloudNativePG. Never place tokens in public app data.
class nest::service::joyride (
  Optional[Sensitive[Hash[String, String]]] $runtime_secrets         = undef,
  Optional[Sensitive[String]]               $registry_dockerconfig   = undef,
  Optional[Sensitive[String]]               $artifact_verifier_token = undef,
) {
  # Only the verified TEST recipe exists. A distinct production contract and
  # owner-approved rollout must be implemented before this boundary is widened.
  if $nest::kubernetes::namespace != 'test' or $nest::kubernetes::service != 'joyride-test' or lookup('runtime_environment', { 'default_value' => undef }) != 'test' {
    fail('Joyride currently supports only service joyride-test in namespace test with runtime_environment test; production is not configured')
  }

  # Reject an unsupported environment before asking for credentials. Optional
  # parameters permit that ordering, not a credential-free TEST deployment.
  if $runtime_secrets == undef or $registry_dockerconfig == undef or $artifact_verifier_token == undef {
    fail('Joyride TEST requires managed runtime, registry and read-only artifact-verifier credentials')
  }

  $django_secret_key_base64      = base64('encode', $runtime_secrets.unwrap['DJANGO_SECRET_KEY']).chomp
  $ops_token_base64              = base64('encode', $runtime_secrets.unwrap['OPS_TOKEN']).chomp
  $delivery_token_base64         = base64('encode', $runtime_secrets.unwrap['DELIVERY_TOKEN']).chomp
  $wmata_api_key_base64          = base64('encode', $runtime_secrets.unwrap['WMATA_API_KEY']).chomp
  $email_host_user_base64        = base64('encode', $runtime_secrets.unwrap['EMAIL_HOST_USER']).chomp
  $email_host_password_base64    = base64('encode', $runtime_secrets.unwrap['EMAIL_HOST_PASSWORD']).chomp
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
  $routing_installer_base64      = base64('encode', file('nest/app/joyride/install_routing_graph.py'))
  $routing_installer_sha256      = sha256(file('nest/app/joyride/install_routing_graph.py'))
  $test_access_config_base64     = base64('encode', file('nest/app/joyride/test-access-nginx.conf'))
  $test_access_config_sha256     = sha256(file('nest/app/joyride/test-access-nginx.conf'))
  $production_ops_config_base64  = base64('encode', file('nest/app/joyride/production-ops-nginx.conf'))
  $production_ops_config_sha256  = sha256(file('nest/app/joyride/production-ops-nginx.conf'))
}
