define nest::lib::llama_server (
  String            $repo,
  Optional[Integer] $instance = undef,
  Stdlib::Port      $port     = 8080,
  Array[String]     $args     = [],
) {
  if $instance {
    $name_real = "${name}-${instance}"
    $port_real = $port + $instance
  } else {
    $name_real = $name
    $port_real = $port
  }

  $command = [
    'llama-server', '-v',
    '--hf-repo', $repo,
    '--host', '0.0.0.0',
  ] + $args

  nest::lib::container { "llama-${name_real}":
    image   => 'nest/tools/llama.cpp',
    command => $command,
    devices => ['/dev/dri/renderD128'],
    publish => ["${port_real}:8080"],
    secrets => { 'llama-server-hf-token' => 'HF_TOKEN' },
    volumes => ["llama-${name_real}-cache:/root/.cache"],
  }
}
