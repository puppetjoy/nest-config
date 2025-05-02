class nest::base::vmware {
  case $facts['os']['family'] {
    'Gentoo': {
      if $facts['profile']['platform'] and $facts['profile']['platform'] =~ /^vmware/ {
        nest::lib::package { 'app-emulation/open-vm-tools':
          ensure => installed,
          use    => 'gtkmm',
        }
        ->
        service { 'vmtoolsd':
          enable => true,
        }

        # For copy/paste and drag-and-drop
        # See: https://kb.vmware.com/s/article/74671
        file { '/etc/systemd/system/run-vmblock\x2dfuse.mount':
          mode   => '0644',
          owner  => 'root',
          group  => 'root',
          source => 'puppet:///modules/nest/vmware/run-vmblock-fuse.mount',
        }
        ~>
        nest::lib::systemd_reload { 'vmware': }
        ->
        service { 'run-vmblock\x2dfuse.mount':
          enable => true,
        }

        # For shared folders
        # See: https://kb.vmware.com/s/article/60262
        Augeas <| title == 'fstab' |> {
          changes +> [
            'set 9/spec vmhgfs-fuse',
            'set 9/file /mnt/hgfs',
            'set 9/vfstype fuse',
            'set 9/opt[1] defaults',
            'set 9/opt[2] allow_other',
            'set 9/dump 0',
            'set 9/passno 0',
          ],
        }
      }
    }

    'windows': {
      # not implemented
    }
  }
}
