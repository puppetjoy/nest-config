class nest::tool::whispercpp (
  String $revision  = 'master',
  String $model_url = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin',
) {
  portage::makeconf { 'video_cards':
    content => '-* intel amdgpu radeonsi',
  }

  nest::lib::package { [
    'dev-util/vulkan-headers',
    'media-libs/shaderc',
    'media-video/ffmpeg',
  ]:
    ensure => installed,
    before => Nest::Lib::Build['whisper.cpp'],
  }

  nest::lib::src_repo { '/usr/src/whisper.cpp':
    url => 'https://github.com/ggml-org/whisper.cpp.git',
    ref => $revision,
  }
  ~>
  nest::lib::build { 'whisper.cpp':
    dir     => '/usr/src/whisper.cpp',
    distcc  => false,
    command => [
      ['cmake -B build -G Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_INSTALL_PREFIX=/usr/local',
        '-DCMAKE_INSTALL_RPATH=/usr/local/lib64',
        '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON',
        '-DWHISPER_COMMON_FFMPEG=ON',
        '-DGGML_RVV=OFF',
        '-DGGML_RV_ZFH=OFF',
        '-DGGML_RV_ZVFH=OFF',
        '-DGGML_RV_ZICBOP=OFF',
        '-DGGML_RV_ZIHINTPAUSE=OFF',
        '-DGGML_VULKAN=ON',
      ].join(' '),
      'cmake --build build',
      'cmake --install build',
      'install -d /usr/local/share/whisper.cpp/models',
      "test -s /usr/local/share/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin || curl -L ${model_url.shellquote} -o /usr/local/share/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin",
      'whisper-server --help >/dev/null',
    ],
    require => Class['nest::base::gpu'],
  }
}
