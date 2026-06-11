define nest::lib::llama_server (
  String              $repo,
  Nest::ServiceEnsure $ensure          = running,
  Optional[Integer]   $instance        = undef,
  Optional[Integer]   $kv_size         = undef,
  Optional[Integer]   $gpu_layers      = undef,
  Optional[Integer]   $parallel        = undef,
  Boolean             $flash_attention = false,
  Optional[String]    $cache_type_k    = undef,
  Optional[String]    $cache_type_v    = undef,
  Array[String]       $extra_args      = [],
  Stdlib::Port        $port            = 8080,
  Stdlib::Port        $port_base       = $port,
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

    $gpu_layers ? {
      undef   => [],
      default => ['--n-gpu-layers', String($gpu_layers)],
    },

    $parallel ? {
      undef   => [],
      default => ['--parallel', String($parallel)],
    },

    $flash_attention ? {
      true    => ['--flash-attn', 'on'],
      default => [],
    },

    $cache_type_k ? {
      undef   => [],
      default => ['--cache-type-k', $cache_type_k],
    },

    $cache_type_v ? {
      undef   => [],
      default => ['--cache-type-v', $cache_type_v],
    },

    $extra_args,
  ].flatten

  nest::lib::container { "llama-${name}":
    ensure  => $ensure,
    image   => 'nest/tools/llama.cpp',
    command => $command,
    devices => ['/dev/dri/renderD128'],
    publish => ["${port_real}:${port_real}"],
    secrets => { 'llama-server-hf-token' => 'HF_TOKEN' },
    volumes => ["llama-${name}-cache:/root/.cache"],
  }
}
