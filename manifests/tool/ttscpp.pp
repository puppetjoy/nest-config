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
    url        => 'https://github.com/mmwillet/TTS.cpp.git',
    ref        => $revision,
    submodules => true,
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
    ],
  }

  exec { 'tts.cpp-install':
    command     => join([
      'install -D -m 0755 build/bin/tts-server /usr/local/bin/tts-server',
      'install -D -m 0755 build/bin/tts-cli /usr/local/bin/tts-cli',
      'install -D -m 0755 build/bin/phonemize /usr/local/bin/tts-phonemize',
      'install -D -m 0755 build/bin/quantize /usr/local/bin/tts-quantize',
    ], ' && '),
    cwd         => '/usr/src/TTS.cpp',
    path        => '/usr/bin:/bin',
    refreshonly => true,
    subscribe   => Exec['tts.cpp-build'],
  }

  file { '/usr/local/share/TTS.cpp':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
  }
  ->
  file { '/usr/local/share/TTS.cpp/models':
    ensure => directory,
    mode   => '0755',
    owner  => 'root',
    group  => 'root',
  }
  ->
  exec { 'tts.cpp-download-kokoro':
    command => "/usr/bin/curl -L ${model_url.shellquote} -o /usr/local/share/TTS.cpp/models/Kokoro_espeak_Q5.gguf",
    creates => '/usr/local/share/TTS.cpp/models/Kokoro_espeak_Q5.gguf',
    path    => '/usr/bin:/bin',
    require => Exec['tts.cpp-install'],
  }

  exec { 'tts.cpp-verify-server':
    command     => '/usr/local/bin/tts-server --help >/dev/null',
    path        => '/usr/local/bin:/usr/bin:/bin',
    refreshonly => true,
    subscribe   => Exec['tts.cpp-install'],
  }
}
