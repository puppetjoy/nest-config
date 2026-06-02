class nest::service::honcho (
  Sensitive $openai_api_key,
) {
  if defined(Class['nest::kubernetes']) {
    $openai_api_key_base64 = base64('encode', $openai_api_key.unwrap)
  }
}
