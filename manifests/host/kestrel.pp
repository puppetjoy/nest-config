class nest::host::kestrel {
  # Host images
  nest::lib::virtual_host { 'nest':
    servername  => 'nest.joyfullee.me',
    ssl         => false,
    zfs_docroot => false,
  }
}
