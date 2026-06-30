class nest::service::camofox {
  if defined(Class['nest::kubernetes']) {
    notice('Camofox Browser service is managed by KubeCM; final purchase remains gated in Hermes secure-browser tooling')
  }
}
