class nest::service::llama_server (
  Sensitive          $hf_token,
  Hash[String, Hash] $instances = {},
) {
  if defined(Class['nest::kubernetes']) {
    $hf_token_base64 = base64('encode', $hf_token.unwrap)
  } else {
    nest::lib::secret { 'llama-server-hf-token':
      value => $hf_token,
    }

    $instances.each |$instance, $attributes| {
      if $attributes['count'] {
        Integer[1, $attributes['count']].each |$i| {
          nest::lib::llama_server { "${instance}${i}":
            instance => $i,
            *        => $attributes - ['count'],
          }
        }
      } else {
        nest::lib::llama_server { $instance:
          * => $attributes,
        }
      }
    }

    Nest::Lib::Secret['llama-server-hf-token']
    -> Nest::Lib::Llama_server <||>
  }
}
