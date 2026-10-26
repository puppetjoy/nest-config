class nest::lib::crossdev {
  nest::lib::package { 'sys-devel/crossdev':
    ensure => installed,
  }

  # Crossdev generates repository content; it is not a fourth pinned input.
  # Keep build output outside the complete frozen /var/db/repos inventory.
  # Ordinary hosts retain their existing location without a live migration.
  $location = ($facts['build'] and $facts['build'] =~ /^stage\d+$/) ? {
    true    => '/var/lib/portage/crossdev',
    default => '/var/db/repos/crossdev',
  }

  nest::lib::repo { 'crossdev':
    location => $location,
  }

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
      tag   => 'profile',
    ;

    [
      "${location}/metadata",
      "${location}/profiles",
    ]:
      ensure => directory,
    ;

    "${location}/metadata/layout.conf":
      content => "masters = gentoo\nthin-manifests = true\n",
    ;

    "${location}/profiles/repo_name":
      content => "crossdev\n",
    ;
  }
}
