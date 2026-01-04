define nest::lib::llama_server (
  String            $repo,
  Optional[Integer] $instance  = undef,
  Optional[Integer] $kv_size   = undef,
  Stdlib::Port      $port      = 8080,
  Stdlib::Port      $port_base = $port,
) {
  if $instance {
    $port_real = $port_base + $instance
  } else {
    $port_real = $port
  }

  $command = [
    'llama-server',
    '--host', '0.0.0.0',
    '--port', String($port_real),
    '--hf-repo', $repo,

    $kv_size ? {
      undef   => [],
      default => ['--ctx-size', String($kv_size)],
    },
  ].flatten

  nest::lib::container { "llama-${name}":
    image   => 'nest/tools/llama.cpp',
    command => $command,
    devices => ['/dev/dri/renderD128'],
    publish => ["${port_real}:${port_real}"],
    secrets => { 'llama-server-hf-token' => 'HF_TOKEN' },
    volumes => ["llama-${name}-cache:/root/.cache"],
  }
}
