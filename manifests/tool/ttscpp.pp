class nest::tool::ttscpp (
  String $revision  = 'main',
  String $model_url = 'https://huggingface.co/mmwillet2/Kokoro_GGUF/resolve/main/Kokoro_espeak_Q5.gguf',
) {
  nest::lib::package { [
    'app-accessibility/espeak-ng',
  ]:
    ensure => installed,
    before => Nest::Lib::Build['tts.cpp'],
  }

  nest::lib::src_repo { '/usr/src/TTS.cpp':
    url => 'https://github.com/mmwillet/TTS.cpp.git',
    ref => $revision,
  }
  ~>
  nest::lib::build { 'tts.cpp':
    dir     => '/usr/src/TTS.cpp',
    distcc  => false,
    command => [
      ['cmake -B build -G Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_INSTALL_PREFIX=/usr/local',
        '-DCMAKE_INSTALL_RPATH=/usr/local/lib64',
        '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON',
      ].join(' '),
      'cmake --build build',
      'cmake --install build',
      'install -d /usr/local/share/TTS.cpp/models',
      "test -s /usr/local/share/TTS.cpp/models/Kokoro_espeak_Q5.gguf || curl -L ${model_url.shellquote} -o /usr/local/share/TTS.cpp/models/Kokoro_espeak_Q5.gguf",
      'tts-server --help >/dev/null',
    ],
  }
}
