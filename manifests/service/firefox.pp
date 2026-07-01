class nest::service::firefox {
  if defined(Class['nest::kubernetes']) {
    notice('Firefox/Kasm secure browser service is managed by KubeCM; automation remains behind reviewed Hermes secure-browser gates')
  }
}
