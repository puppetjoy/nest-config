class nest::tool::llamacpp (
  String        $revision             = 'master',
  Boolean       $build_rocm           = ($facts.dig('profile', 'cpu') == 'zen5'),
  Array[String] $rocm_amdgpu_targets  = ['gfx1151'],
) {
  $build_rocm_real = $build_rocm and ($facts.dig('profile', 'cpu') == 'zen5')
  $rocm_commands = $build_rocm_real ? {
    true    => [
      ['cmake -S . -B build-rocm -G Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_INSTALL_PREFIX=/usr/local',
        '-DCMAKE_INSTALL_RPATH=/usr/local/lib64',
        '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON',
        '-DBUILD_SHARED_LIBS=OFF',
        '-DGGML_RVV=OFF',
        '-DGGML_RV_ZFH=OFF',
        '-DGGML_RV_ZVFH=OFF',
        '-DGGML_RV_ZICBOP=OFF',
        '-DGGML_RV_ZIHINTPAUSE=OFF',
        '-DGGML_VULKAN=OFF',
        '-DGGML_HIP=ON',
        "'-DAMDGPU_TARGETS=${rocm_amdgpu_targets.join(';')}'",
        '-DLLAMA_OPENSSL=ON',
      ].join(' '),
      'cmake --build build-rocm --target llama-server',
      'install -Dm0755 build-rocm/bin/llama-server /usr/local/bin/llama-server-rocm',
    ],
    default => [],
  }
  $rocm_packages = $build_rocm_real ? {
    true    => ['dev-util/hip', 'dev-util/hipcc', 'dev-util/rocminfo'],
    default => [],
  }

  portage::makeconf { 'video_cards':
    content => 'intel amdgpu radeonsi',
  }

  nest::lib::package { [
    'dev-libs/openssl',
    'dev-util/spirv-headers',
    'dev-util/vulkan-headers',
    'media-libs/shaderc',
  ] + $rocm_packages:
    ensure => installed,
    before => Nest::Lib::Build['llama.cpp'],
  }

  nest::lib::src_repo { '/usr/src/llama.cpp':
    url => 'https://github.com/ggml-org/llama.cpp.git',
    ref => $revision,
  }
  ~>
  nest::lib::build { 'llama.cpp':
    dir     => '/usr/src/llama.cpp',
    distcc  => false,
    command => [
      ['cmake -S . -B build-vulkan -G Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_INSTALL_PREFIX=/usr/local',
        '-DCMAKE_INSTALL_RPATH=/usr/local/lib64',
        '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON',
        '-DBUILD_SHARED_LIBS=OFF',
        '-DGGML_RVV=OFF',
        '-DGGML_RV_ZFH=OFF',
        '-DGGML_RV_ZVFH=OFF',
        '-DGGML_RV_ZICBOP=OFF',
        '-DGGML_RV_ZIHINTPAUSE=OFF',
        '-DGGML_VULKAN=ON',
        '-DGGML_HIP=OFF',
        '-DLLAMA_OPENSSL=ON',
      ].join(' '),
      'cmake --build build-vulkan --target llama-server',
      'install -Dm0755 build-vulkan/bin/llama-server /usr/local/bin/llama-server-vulkan',
      'ln -sf llama-server-vulkan /usr/local/bin/llama-server',
    ] + $rocm_commands,
    require => Class['nest::base::gpu'],
  }
}
