class nest::service::kasm_shopping_browser (
  Sensitive[String] $vnc_password,
) {
  if defined(Class['nest::kubernetes']) {
    $vnc_password_base64 = base64('encode', $vnc_password.unwrap)
  }
}
