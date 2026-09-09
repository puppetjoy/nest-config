class nest::service::firefox {
  if defined(Class['nest::kubernetes']) {
    notice('Firefox/Kasm persistent browser is managed by KubeCM; Star control uses the owner-visible OS accessibility/UI bridge')
  }
}
