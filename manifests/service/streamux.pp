class nest::service::streamux (
  String $ssid,
  Sensitive $password,
) {
  include nest::service::bluetooth

  #
  # Firewall
  #
  firewalld_zone { 'streamux':
    ensure     => present,
    interfaces => 'wlan0',
    target     => 'default',
  }

  Firewalld_policy <| title == 'nat' |> {
    ingress_zones +> 'streamux',
  }

  Firewalld_port {
    zone => 'streamux',
  }

  Firewalld_service {
    zone => 'streamux',
  }

  #
  # Hostapd
  #
  nest::lib::package { 'net-wireless/hostapd':
    ensure => installed,
  }
  ->
  file { '/etc/hostapd/hostapd.conf':
    mode    => '0600',
    owner   => 'root',
    group   => 'root',
    content => epp('nest/streamux/hostapd.conf.epp'),
  }
  ~>
  service { 'hostapd':
    enable => true,
  }

  #
  # Dnsmasq
  #
  class { 'nest::service::dnsmasq':
    interfaces => ['wlan0'],
  }

  # Hand out IPs in order, but start over every reboot
  $dnsmasq_conf = @(DNSMASQ)
    dhcp-leasefile=/run/dnsmasq.leases
    dhcp-range=172.22.100.100,172.22.100.199,infinite
    dhcp-sequential-ip
    | DNSMASQ

  file { '/etc/dnsmasq.d/streamux.conf':
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    content => $dnsmasq_conf,
    notify  => Service['dnsmasq'],
  }

  firewalld_service { ['dhcp', 'dns']:
    ensure => present,
  }

  #
  # Nginx
  #
  nest::lib::package_use { 'app-misc/mime-types':
    use => 'nginx',
  }
  ->
  nest::lib::package { 'www-servers/nginx':
    ensure => installed,
    use    => 'rtmp',
  }

  firewalld_port {
    'rtmp':
      ensure   => present,
      port     => 1935,
      protocol => 'tcp',
    ;

    'hls':
      ensure   => present,
      port     => 8080,
      protocol => 'tcp',
      zone     => 'external',
    ;
  }

  #
  # Gstreamer
  #
  nest::lib::package { [
    'media-libs/gst-plugins-bad',
    'media-libs/gst-plugins-good',
    'media-plugins/gst-plugins-rtmp',
    'media-plugins/gst-plugins-v4l2codecs',
    'media-plugins/gst-plugins-x264',
  ]:
    ensure => installed,
  }

  #
  # Streamux
  #
  vcsrepo { "/home/${nest::user}/streamux":
    ensure   => latest,
    provider => git,
    source   => 'https://gitlab.james.tl/joy/streamux.git',
    revision => 'main',
    user     => $nest::user,
  }

  # For speedometer
  nest::lib::package { 'dev-python/urwid':
    ensure => installed,
  }

  # For access to /dev/video0 hardware acceleration
  User <| title == $nest::user |> {
    groups +> 'video',
  }

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/systemd/system/mnt-external.automount':
      source => 'puppet:///modules/nest/streamux/mnt-external.automount',
    ;

    '/etc/systemd/system/mnt-external.mount':
      source => 'puppet:///modules/nest/streamux/mnt-external.mount',
    ;
  }
  ~>
  nest::lib::systemd_reload { 'streamux': }
  ->
  service { 'mnt-external.automount':
    enable => true,
  }
}
