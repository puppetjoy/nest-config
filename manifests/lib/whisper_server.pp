define nest::lib::whisper_server (
  String              $model      = '/usr/local/share/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin',
  Nest::ServiceEnsure $ensure     = running,
  Optional[Integer]   $processors = undef,
  Optional[Integer]   $threads    = undef,
  Stdlib::Port        $port       = 2022,
) {
  $command = [
    'whisper-server',
    '--model', $model,
    '--host', '0.0.0.0',
    '--port', String($port),
    '--inference-path', '/v1/audio/transcriptions',
    '--convert',

    $processors ? {
      undef   => [],
      default => ['--processors', String($processors)],
    },

    $threads ? {
      undef   => [],
      default => ['--threads', String($threads)],
    },
  ].flatten

  nest::lib::container { "whisper-${name}":
    ensure  => $ensure,
    image   => 'nest/tools/whisper.cpp',
    command => $command,
    devices => ['/dev/dri/renderD128'],
    publish => ["${port}:${port}"],
    volumes => ["whisper-${name}-cache:/root/.cache"],
  }
}
