class nest::service::rocm {
  if $facts['os']['family'] == 'Gentoo' {
    # ROCm/HIP needs the AMDGPU Portage video card selected even on
    # headless Kubernetes workers. Keep this local to hosts that opt in
    # to the ROCm service instead of changing every Gentoo node.
    portage::makeconf { 'video_cards':
      content => 'amdgpu radeonsi',
    }

    nest::lib::package { [
      'dev-util/hip',
      'dev-util/hipcc',
      'dev-util/rocminfo',
    ]:
      ensure => installed,
    }

    User <| title == $nest::user |> {
      groups +> ['render', 'video'],
    }
  }
}
