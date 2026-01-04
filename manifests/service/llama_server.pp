class nest::service::llama_server (
  Sensitive          $hf_token,
  Hash[String, Hash] $instances  = {},
) {
  if defined(Class['nest::kubernetes']) {
    $hf_token_base64 = base64('encode', $hf_token.unwrap)
  } else {
    nest::lib::secret { 'llama-server-hf-token':
      value => $hf_token,
    }

    $instances.each |$instance, $attributes| {
      nest::lib::llama_server { $instance:
        *       => $attributes,
        require => Nest::Lib::Secret['llama-server-hf-token'],
      }
    }
  }
}
