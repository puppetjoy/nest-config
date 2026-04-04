class nest::base::gpu {
  $video_cards = ($facts['portage_video_cards'].split(' ') + $nest::use.filter |$use_flag| {
    $use_flag =~ /^video_cards_/
  }.map |$use_flag| {
    regsubst($use_flag, '^video_cards_', '')
  }).sort.unique

  if 'nvidia' in $video_cards {
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
    nest::lib::package { 'sys-power/switcheroo-control':
      ensure => installed,
    }
    ->
    service { 'switcheroo-control':
      enable => true,
    }
  }

  if 'vulkan' in [$facts['portage_use'].split(' '), $nest::use].flatten {
    nest::lib::package { [
      'dev-util/vulkan-tools',
      'media-libs/mesa',
      'media-libs/vulkan-loader',
    ]:
      ensure => installed,
    }

    User <| title == $nest::user |> {
      groups +> 'render',
    }
  }

  if 'amdgpu' in $video_cards {
    nest::lib::package { 'sys-apps/amdgpu_top':
      ensure   => installed,
      unstable => true,
    }
  }

  if ['amdgpu', 'intel', 'nvidia'].any |$video_card| { $video_card in $video_cards } {
    nest::lib::package { 'sys-process/nvtop':
      ensure => installed,
    }
  }
}
