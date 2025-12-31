class nest::tool::rocm {
  include 'nest' # for nest::user

  User <| title == $nest::user |> {
    groups +> ['render', 'video'],
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

  # AMD SMI expects cpuid.h which is not available on RISC-V
  unless $facts['profile']['architecture'] == 'riscv' {
    package_accept_keywords { 'dev-libs/rocm-core':
      tag => 'profile',
    }
    ->
    nest::lib::package { 'dev-util/amdsmi':
      ensure   => installed,
      unstable => true,
    }
  }

  nest::lib::package { 'sys-apps/amdgpu_top':
    ensure   => installed,
    unstable => true,
  }
}
