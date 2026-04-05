define nest::lib::dconf (
  Hash[String, Hash[String, String]] $settings,
  Variant[Boolean, Array[String]]    $locks    = false,
  String[1]                          $database = 'local',
) {
  include nest::base::dconf

  $resource_name = regsubst($name, '[^a-zA-Z0-9._-]+', '-', 'G')

  $lock_paths = $locks ? {
    true    => $settings.reduce([]) |$memo, $section_entry| {
      $section = $section_entry[0]
      $memo + $section_entry[1].keys.map |$key| { "/${section}/${key}" }
    },
    false   => [],
    default => $locks,
  }

  file { "/etc/dconf/db/${database}.d/${resource_name}":
    ensure  => file,
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => epp('nest/dconf/settings.epp', { 'settings' => $settings }),
    notify  => Class['nest::base::dconf'],
  }

  unless empty($lock_paths) {
    file { "/etc/dconf/db/${database}.d/locks/${resource_name}":
      ensure  => file,
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => epp('nest/dconf/locks.epp', { 'locks' => $lock_paths }),
      notify  => Class['nest::base::dconf'],
    }
  }
}
