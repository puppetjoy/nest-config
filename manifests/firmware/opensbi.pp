class nest::firmware::opensbi {
  unless $nest::opensbi_tag {
    fail("'opensbi_tag' is not set")
  }

  case $facts['profile']['platform'] {
    'milkv-mars': {
      # See: https://docs.u-boot.org/en/latest/board/starfive/milk-v_mars.html
      $build_options = 'FW_TEXT_START=0x40000000 FW_OPTIONS=0'
    }

    default: {
      $build_options = ''
    }
  }

  nest::lib::src_repo { '/usr/src/opensbi':
    url => 'https://gitlab.james.tl/nest/forks/opensbi.git',
    ref => $nest::opensbi_tag,
  }
  ~>
  nest::lib::build { 'opensbi':
    args => "PLATFORM=generic BUILD_INFO=y ${build_options}",
    dir  => '/usr/src/opensbi',
  }
}
