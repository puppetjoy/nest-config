define nest::lib::secret (
  Sensitive $value,
) {
  unless $facts['is_container'] {
    require 'nest::base::containers'

    exec { "create-podman-secret-${name}":
      command     => "/usr/bin/podman secret create --env ${name} SECRET_VALUE",
      environment => "SECRET_VALUE=${value.unwrap}",
      unless      => "/usr/bin/podman secret inspect ${name} >/dev/null 2>&1",
    }
  }
}
