class nest::service::ipxe (
  String $servername,
) {
  unless $facts['is_container'] {
    zfs { "${facts['rpool']}/export":
      mountpoint => '/export',
      sharenfs   => 'rw,no_root_squash',
    }
    ->
    zfs { "${facts['rpool']}/export/hosts":
      before => Nest::Lib::Virtual_host['ipxe'],
    }
  }

  nest::lib::virtual_host { 'ipxe':
    servername => $servername,
    docroot    => '/export/hosts',
    ssl        => false,
  }

  nest::lib::external_service { ['http', 'nfs']: }
}
