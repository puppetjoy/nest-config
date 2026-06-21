class nest::tool::llamacpp (
  String        $revision             = 'master',
  Boolean       $build_rocm           = ($facts.dig('profile', 'cpu') == 'zen5'),
  Array[String] $rocm_amdgpu_targets  = ['gfx1151'],
) {
  $build_rocm_real = $build_rocm and ($facts.dig('profile', 'cpu') == 'zen5')
  $rocm_targets = ['llama-server', 'llama-bench']
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
        '-DGGML_HIP_ROCWMMA_FATTN=OFF',
        "'-DAMDGPU_TARGETS=${rocm_amdgpu_targets.join(';')}'",
        '-DLLAMA_OPENSSL=ON',
      ].join(' '),
      "cmake --build build-rocm --target ${rocm_targets.join(' ')}",
    ],
    default => [],
  }
  $rocm_packages = $build_rocm_real ? {
    true    => ['dev-util/hip', 'dev-util/hipcc', 'dev-util/rocminfo', 'sci-libs/hipBLAS', 'sci-libs/hipBLAS-common'],
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
      'cmake --build build-vulkan --target llama-server llama-bench',
    ] + $rocm_commands,
    require => Class['nest::base::gpu'],
  }

  file { '/usr/local/bin/llama-server-vulkan':
    ensure  => file,
    source  => '/usr/src/llama.cpp/build-vulkan/bin/llama-server',
    mode    => '0755',
    require => Nest::Lib::Build['llama.cpp'],
  }

  file { '/usr/local/bin/llama-bench-vulkan':
    ensure  => file,
    source  => '/usr/src/llama.cpp/build-vulkan/bin/llama-bench',
    mode    => '0755',
    require => Nest::Lib::Build['llama.cpp'],
  }

  file { '/usr/local/bin/llama-server':
    ensure  => link,
    target  => 'llama-server-vulkan',
    require => File['/usr/local/bin/llama-server-vulkan'],
  }

  if $build_rocm_real {
    file { '/usr/local/bin/llama-server-rocm':
      ensure  => file,
      source  => '/usr/src/llama.cpp/build-rocm/bin/llama-server',
      mode    => '0755',
      require => Nest::Lib::Build['llama.cpp'],
    }

    file { '/usr/local/bin/llama-bench-rocm':
      ensure  => file,
      source  => '/usr/src/llama.cpp/build-rocm/bin/llama-bench',
      mode    => '0755',
      require => Nest::Lib::Build['llama.cpp'],
    }
  }

  file { '/usr/src/llama.cpp/build-vulkan':
    ensure  => absent,
    force   => true,
    recurse => true,
    require => [
      File['/usr/local/bin/llama-server-vulkan'],
      File['/usr/local/bin/llama-bench-vulkan'],
    ],
  }

  if $build_rocm_real {
    file { '/usr/src/llama.cpp/build-rocm':
      ensure  => absent,
      force   => true,
      recurse => true,
      require => [
        File['/usr/local/bin/llama-server-rocm'],
        File['/usr/local/bin/llama-bench-rocm'],
      ],
    }
  }

  file { '/usr/lib/debug':
    ensure  => absent,
    force   => true,
    recurse => true,
    require => Nest::Lib::Build['llama.cpp'],
  }
}
