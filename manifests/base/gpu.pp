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

  if $facts['portage_video_cards'] {
    $video_cards = $facts['portage_video_cards'].split(' ')

    if 'amdgpu' in $video_cards {
      nest::lib::package { 'sys-apps/amdgpu_top':
        ensure   => installed,
        unstable => true,
      }
    }

    if 'intel' in $video_cards {
      nest::lib::package { 'x11-apps/igt-gpu-tools':
        ensure   => installed,
        unstable => true,
      }
    }
  }
}
