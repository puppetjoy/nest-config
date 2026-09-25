class nest::host::kestrel (
  Sensitive[String[1]] $cloudns_dynamic_url,
) {
  # Host images
  nest::lib::virtual_host { 'nest':
    servername  => 'nest.joyfullee.me',
    ssl         => false,
    zfs_docroot => false,
  }

  # CloudNS Dynamic URL is a credential. Keep it out of unit files, argv and reports.
  file { '/etc/nest/cloudns-home.url':
    ensure    => file,
    owner     => 'root',
    group     => 'root',
    mode      => '0600',
    content   => $cloudns_dynamic_url,
    show_diff => false,
    require   => File['/etc/nest'],
  }

  file { '/usr/local/sbin/cloudns-home-update':
    ensure => file,
    owner  => 'root',
    group  => 'root',
    mode   => '0755',
    source => 'puppet:///modules/nest/scripts/cloudns-home-update.py',
  }

  systemd::manage_unit { 'cloudns-home-update.service':
    unit_entry    => {
      'Description' => 'Update home.joyfullee.me via CloudNS',
      'After'       => 'network-online.target',
      'Wants'       => 'network-online.target',
    },
    service_entry => {
      'Type'            => 'oneshot',
      'ExecStart'       => '/usr/local/sbin/cloudns-home-update',
      'TimeoutStartSec' => '45s',
      'PrivateTmp'      => true,
      'ProtectSystem'   => 'strict',
      'ProtectHome'     => true,
    },
    require       => [File['/etc/nest/cloudns-home.url'], File['/usr/local/sbin/cloudns-home-update']],
  }

  systemd::manage_unit { 'cloudns-home-update.timer':
    unit_entry    => {
      'Description' => 'Refresh home.joyfullee.me every five minutes',
    },
    timer_entry   => {
      'OnBootSec'       => '1min',
      'OnUnitActiveSec' => '5min',
      'Unit'            => 'cloudns-home-update.service',
    },
    install_entry => {
      'WantedBy' => 'timers.target',
    },
    require       => Systemd::Manage_unit['cloudns-home-update.service'],
  }

  service { 'cloudns-home-update.timer':
    ensure  => running,
    enable  => true,
    require => Systemd::Manage_unit['cloudns-home-update.timer'],
  }
}
