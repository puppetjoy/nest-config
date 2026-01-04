define nest::lib::llama_server (
  Stdlib::Port  $port,
  String        $repo,
  Array[String] $args = [],
) {
  $command = [
    'llama-server', '-v',
    '--hf-repo', $repo,
    '--host', '0.0.0.0',
  ] + $args

  nest::lib::container { "llama-${name}":
    image   => 'nest/tools/llama.cpp',
    command => $command,
    devices => ['/dev/dri/renderD128'],
    publish => ["${port}:8080"],
    secrets => { 'llama-server-hf-token' => 'HF_TOKEN' },
    volumes => ["llama-${name}-cache:/root/.cache"],
  }
}
