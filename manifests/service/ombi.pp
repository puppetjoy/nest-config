class nest::service::ombi {
  # Required for media user
  include 'nest'

  nest::lib::srv { 'ombi':
    mode  => '0755',
    owner => 'media',
    group => 'media',
  }
  ->
  file { '/srv/ombi/config':
    ensure => directory,
    mode   => '0755',
    owner  => 'media',
    group  => 'media',
  }
  ->
  nest::lib::container { 'ombi':
    image   => 'linuxserver/ombi',
    dns     => '172.22.4.3',
    env     => ['PUID=1001', 'PGID=1001', 'TZ=America/New_York'],
    publish => ['3579:3579'],
    volumes => ['/srv/ombi/config:/config'],
  }
}
