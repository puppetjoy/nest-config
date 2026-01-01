class nest::base::gpu {
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

  if $facts['portage_video_cards'] and 'amdgpu' in $facts['portage_video_cards'].split(' ') {
    nest::lib::package { 'sys-apps/amdgpu_top':
      ensure   => installed,
      unstable => true,
    }
  }
}
