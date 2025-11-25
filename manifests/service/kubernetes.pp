class nest::service::kubernetes (
  Sensitive $bolt_private_key,
  Boolean $control_plane = false,
) {
  include nest
  include nest::base::bird

  File {
    mode  => '0644',
    owner => 'root',
    group => 'root',
  }

  # Install and enable container runtime
  nest::lib::package { 'app-containers/cri-o':
    ensure => installed,
  }
  ->
  file {
    '/etc/crio/crio.conf.d':
      ensure => directory;
    '/etc/crio/crio.conf.d/10-crun.conf':
      source => 'puppet:///modules/nest/kubernetes/crio-crun.conf',
    ;
  }
  ~>
  service { 'crio':
    enable => true,
  }

  # Install and enable kubelet with a service that works with CRI-O and kubeadm
  nest::lib::package { 'sys-cluster/kubelet':
    ensure => installed,
  }
  ->
  file { '/etc/kubernetes/kubelet.env':
    content => epp('nest/kubernetes/kubelet.env.epp'),
    notify  => Service['kubelet'],
  }

  file { '/etc/systemd/system/kubelet.service':
    source => 'puppet:///modules/nest/kubernetes/kubelet.service',
  }
  ~>
  nest::lib::systemd_reload { 'kubernetes': }
  ->
  service { 'kubelet':
    enable => true,
  }

  # Install management tools
  nest::lib::package { [
    'app-containers/cri-tools',
    'sys-cluster/ipvsadm',
    'sys-cluster/kubeadm',
  ]:
    ensure => installed,
  }

  sysctl {
    'net.ipv4.ip_forward':
      ensure => present,
      value  => '1',
    ;

    # Increase max user instances for kubectl log following
    # see: https://github.com/kairos-io/kairos/issues/2071
    'fs.inotify.max_user_instances':
      ensure => present,
      value  => '8192', # default 128
    ;
  }

  # Allow forwarding and control access between networks used by Kubernetes
  Firewalld_zone <| title == 'external' |> {
    masquerade => true,
    sources    +> [
      '10.96.0.0/12',   # K8s service network
      '192.168.0.0/16', # Calico pod network
      '172.22.0.0/24',  # Nest VPN
      "${facts['networking']['network']}/${facts['networking']['netmask']}", # Host pod network
    ],
    target     => 'default',
  }

  Firewalld_port {
    zone => 'external',
  }

  Firewalld_service {
    zone => 'external',
  }

  Firewalld_rich_rule {
    zone => 'external',
  }

  if $control_plane {
    firewalld_service { 'kube-control-plane':
      ensure => present,
    }

    service { 'nfs-server':
      enable => true,
    }

    service { 'zfs-share':
      enable  => true,
      require => Nest::Lib::Package['sys-fs/zfs'],
    }

    firewalld_service { 'nfs':
      ensure => present,
      zone   => 'external',
    }

    file {
      default:
        mode  => '0644',
        owner => 'root',
        group => 'root',
      ;

      '/etc/systemd/system/kubelet.service.d':
        ensure => directory,
      ;

      '/etc/systemd/system/kubelet.service.d/10-require-etcd-mount.conf':
        content => "[Service]\nExecCondition=/usr/sbin/mountpoint -q /var/lib/etcd\n",
      ;
    }
  } else {
    firewalld_service { 'kubelet-worker':
      ensure => present,
    }
  }

  firewalld_service { 'kubelet':
    ensure => present,
  }

  # Allow BGP for kube-vip
  firewalld_service { 'bgp':
    ensure => present,
  }

  # Allow cluster access to Calico
  firewalld_custom_service { 'calico':
    ensure => present,
    ports  => [
      { 'port' => 1790, 'protocol' => 'tcp' }, # BGP
      { 'port' => 5473, 'protocol' => 'tcp' }, # Typha
    ],
  }
  ->
  firewalld_service { 'calico':
    ensure => present,
  }

  firewalld_rich_rule {
    default:
      ensure => present,
      action => accept,
    ;

    # Allow internal networks
    'nest':
      source => '172.22.0.0/24';
    'eyrie':
      source => '172.22.4.0/24',
    ;
  }

  file { '/usr/local/bin/calicoctl':
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => "https://github.com/projectcalico/calico/releases/download/v3.27.0/calicoctl-linux-${facts['profile']['architecture']}",
    replace => false,
  }

  # For internal bolt usage
  file { '/root/.ssh/id_ed25519_eyrie':
    mode      => '0600',
    owner     => 'root',
    content   => $bolt_private_key,
    show_diff => false,
    require   => Class['nest::base::users'],
  }
}
