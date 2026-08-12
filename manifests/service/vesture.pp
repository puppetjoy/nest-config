class nest::service::vesture (
  String $secret_key,
  String $star_tokens,
) {
  if defined(Class['nest::kubernetes']) {
    notice('Vesture private wardrobe service is managed by KubeCM')
  }
}
