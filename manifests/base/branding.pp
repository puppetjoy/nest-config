class nest::base::branding {
  tag 'profile'

  $variant = $facts['profile']['variant'] ? {
    'server'      => 'Server',
    'workstation' => 'Workstation',
    default       => fail("Unhandled variant ${facts['profile']['variant']}"),
  }

  $image_id = $facts['build'] ? {
    /^stage/ => $facts['build'],
    default  => $facts['release']['image_id'],
  }

  $os_release_content = epp('nest/branding/os-release.epp', {
    variant    => $variant,
    variant_id => $facts['profile']['variant'],
    build_id   => pick_default($facts['ci_job_id'], $facts['release']['build_id']),
    image_id   => $image_id,
  })

  file { '/etc/os-release':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $os_release_content,
  }

  # For os.distro facts
  nest::lib::package { 'sys-apps/lsb-release':
    ensure => installed,
  }
}
