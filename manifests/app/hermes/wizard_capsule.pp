# Inert source installation, independently opt-in from Wizard activation.
# No production capsule, UID, quota, dataset, mount, service or policy is selected.
class nest::app::hermes::wizard_capsule {
  $source_dir = "${nest::app::hermes::install_dir}/capsule"

  file { $source_dir:
    ensure => directory,
    owner  => 'root',
    group  => 'root',
    mode   => '0755',
  }

  ['wizard_capsule.py', 'wizard_capsule_supervisor.py'].each |String $name| {
    file { "${source_dir}/${name}":
      ensure  => file,
      source  => "puppet:///modules/nest/app/hermes/${name}",
      owner   => 'root',
      group   => 'root',
      mode    => '0644',
      require => File[$source_dir],
    }
  }
}
