class nest::tool::amdgpu {
  include 'nest' # for nest::user

  User <| title == $nest::user |> {
    groups +> 'render',
  }

  package_accept_keywords { [
    'dev-build/rocm-cmake',
    'dev-libs/rocm-device-libs',
    'dev-libs/rocr-runtime',
    'dev-libs/roct-thunk-interface',
  ]:
    tag => 'profile',
  }
  ->
  nest::lib::package { 'dev-util/rocminfo':
    ensure   => installed,
    unstable => true,
  }

  nest::lib::package { 'dev-util/rocm-smi':
    ensure   => installed,
    unstable => true,
  }

  nest::lib::package { 'sys-apps/amdgpu_top':
    ensure   => installed,
    unstable => true,
  }
}
