class nest::service::registry (
  Sensitive $admin_password,
) {
  if defined(Class['nest::kubernetes']) {
    $admin_password_base64 = base64('encode', $admin_password.unwrap)
    $admin_salt = fqdn_rand_string(22, undef, "${nest::kubernetes::service_name}-admin")
    $admin_password_hash = pw_hash($admin_password, 'bcrypt', "05\$${admin_salt}")

    # Bucket defined in registry-resources.yaml
    $bucket_config = nest::kubernetes::bucket_config('registry-bucket')

    # Random value used for load balancing
    $http_secret = fqdn_rand_string(32, undef, "${nest::kubernetes::service_name}-http")

    # Random value used for cryptographic functions
    # Ok if this changes, but reduce changes by deploying separately from app
    # See: https://github.com/klausmeyer/docker-registry-browser/blob/master/docs/README.md#secret_key_base
    $ui_secret = base64('encode', generate('/usr/bin/openssl', 'rand', '-hex', '64').chomp)
  }
}
