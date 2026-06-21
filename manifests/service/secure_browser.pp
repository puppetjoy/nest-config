class nest::service::secure_browser {
  if defined(Class['nest::kubernetes']) {
    notice('Secure browser service is managed by KubeCM without a front-door HTTP Basic Auth password')
  }
}
