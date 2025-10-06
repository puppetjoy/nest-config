class nest::base::packages {
  case $facts['os']['family'] {
    'Gentoo': {
      nest::lib::package { [
        'app-admin/eclean-kernel',
        'app-admin/helm',
        'app-admin/sysstat',
        'app-editors/vim',
        'app-misc/jq',
        'app-misc/tmux',
        'app-portage/genlop',
        'app-portage/gentoolkit',
        'dev-debug/strace',
        'dev-libs/libisoburn',
        'net-analyzer/openbsd-netcat',
        'net-dns/bind-tools',
        'net-misc/iperf',
        'net-misc/whois',
        'sys-apps/ethtool',
        'sys-apps/gptfdisk',
        'sys-apps/ipmitool',
        'sys-apps/pciutils',
        'sys-apps/pv',
        'sys-apps/usbutils',
        'sys-block/parted',
        'sys-fs/dosfstools',
        'sys-fs/exfatprogs',
        'sys-fs/mtools',
        'sys-fs/squashfs-tools',
        'sys-libs/nss_wrapper',
        'sys-cluster/kubectl',
        'sys-process/htop',
        'sys-process/iotop',
        'sys-process/lsof',
        'x11-apps/xauth',
        'x11-misc/xsel',
      ]:
        ensure => installed,
      }

      unless $facts['profile']['architecture'] == 'arm' {
        nest::lib::package { 'llvm-core/lld':
          ensure => installed,
        }

        unless defined(Package['virtual/mysql']) { # mysql module
          nest::lib::package { 'dev-db/mariadb':
            ensure => installed,
            use    => '-server',
          }
        }
      }

      unless $facts['profile']['platform'] == 'beagleboneblack' {
        nest::lib::package { 'sys-process/parallel':
          ensure => installed,
        }
      }

      if $facts['profile']['platform'] in ['milkv-pioneer', 'pine64', 'pinebookpro', 'rock4', 'rock5', 'rockpro64', 'sopine'] {
        nest::lib::package { 'sys-fs/mtd-utils':
          ensure => installed,
        }
      }

      if $facts['profile']['platform'] in ['haswell', 'milkv-pioneer', 'raspberrypi5', 'rock4', 'rock5'] {
        nest::lib::package { 'sys-apps/nvme-cli':
          ensure => installed,
        }
      }

      # Python is part of Gentoo base
      # Define this resource for compatibility with puppet-python module
      package { 'python':
        name => 'dev-lang/python',
      }
    }

    'windows': {
      package { [
        'cygutils-extra',
        'netcat',
        'procps-ng',
        'tmux',
        'vim',
        'wget',
      ]:
        ensure   => installed,
        provider => 'cygwin',
      }
    }
  }
}
