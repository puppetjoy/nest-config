function nest::kubernetes::bucket_user(String $object_store, String $user, String $namespace = $nest::kubernetes::namespace) >> Optional[Hash] {
  $kubectl_get_secret = "kubectl get secret -n ${namespace} rook-ceph-object-user-${object_store}-${user} -o json 2>/dev/null || echo '{}'"
  $secret = generate('/bin/sh', '-c', $kubectl_get_secret).parsejson

  if $secret['data'] {
    $secret['data'].reduce({}) |$memo, $kv| {
      $memo + { $kv[0] => base64('decode', $kv[1]) }
    }
  }
}
