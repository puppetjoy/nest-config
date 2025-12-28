class nest::tool::rocm {
  include 'nest' # for nest::user

  package_accept_keywords { [
    'dev-build/rocm-cmake',
    'dev-libs/rocm-device-libs',
    'dev-libs/rocr-runtime',
    'dev-libs/roct-thunk-interface',
    'dev-util/rocminfo',
  ]:
    tag => 'profile',
  }
  ->
  nest::lib::package { 'dev-util/rocminfo':
    ensure => installed,
  }

  User <| title == $nest::user |> {
    groups +> 'render',
  }
}
