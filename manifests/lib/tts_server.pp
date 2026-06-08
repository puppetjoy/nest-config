define nest::lib::tts_server (
  String              $model   = '/usr/local/share/TTS.cpp/models/Kokoro_espeak_Q5.gguf',
  Nest::ServiceEnsure $ensure  = running,
  Optional[Integer]   $threads = undef,
  Stdlib::Port        $port    = 2023,
  String              $voice   = 'af_heart',
) {
  $command = [
    'tts-server',
    '--model-path', $model,
    '--host', '0.0.0.0',
    '--port', String($port),
    '--voice', $voice,

    $threads ? {
      undef   => [],
      default => ['--n-threads', String($threads)],
    },
  ].flatten

  nest::lib::container { "tts-${name}":
    ensure  => $ensure,
    image   => 'nest/tools/tts.cpp',
    command => $command,
    publish => ["${port}:${port}"],
  }
}
