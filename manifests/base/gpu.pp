class nest::base::gpu {
  if 'nvidia' in $facts['portage_video_cards'].split(' ') or 'video_cards_nvidia' in $nest::use {
    nest::lib::package { 'x11-drivers/nvidia-drivers':
      ensure  => installed,
      binpkg  => false,
      require => Class['nest::base::kernel'],
    }

    User <| title == $nest::user |> {
      groups +> 'video',
    }
  }

  if $nest::kernel_config['CONFIG_VGA_SWITCHEROO'] {
    service { 'switcheroo-control':
      enable => true,
    }
  }

  if 'vulkan' in [$facts['portage_use'].split(' '), $nest::use].flatten {
    User <| title == $nest::user |> {
      groups +> 'render',
    }

    nest::lib::package { [
      'dev-util/vulkan-tools',
      'media-libs/mesa',
      'media-libs/vulkan-loader',
    ]:
      ensure => installed,
    }
  }

  if 'amdgpu' in $facts['portage_video_cards'].split(' ') {
    nest::lib::package { 'sys-apps/amdgpu_top':
      ensure   => installed,
      unstable => true,
    }
  }

  nest::lib::package { 'sys-process/nvtop':
    ensure => installed,
  }
}
