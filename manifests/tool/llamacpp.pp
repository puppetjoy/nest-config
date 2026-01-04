class nest::tool::llamacpp (
  String $tag = 'master',
) {
  portage::makeconf { 'video_cards':
    content => '-* intel amdgpu radeonsi',
  }

  nest::lib::package { [
    'dev-util/vulkan-headers',
    'media-libs/shaderc',
  ]:
    ensure => installed,
    before => Nest::Lib::Build['llama.cpp'],
  }

  nest::lib::src_repo { '/usr/src/llama.cpp':
    url => 'https://github.com/ggml-org/llama.cpp.git',
    ref => $tag,
  }
  ~>
  nest::lib::build { 'llama.cpp':
    dir     => '/usr/src/llama.cpp',
    distcc  => false,
    command => [
      ['cmake -B build -G Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_INSTALL_PREFIX=/usr/local',
        '-DCMAKE_INSTALL_RPATH=/usr/local/lib64',
        '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON',
        '-DGGML_RVV=OFF',
        '-DGGML_VULKAN=ON',
      ].join(' '),
      'cmake --build build',
      'cmake --install build',
    ],
    require => Class['nest::base::gpu'],
  }
}
