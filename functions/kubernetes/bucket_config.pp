function nest::kubernetes::bucket_config(String $name, String $namespace = $nest::kubernetes::namespace) >> Optional[Hash] {
  $kubectl_get_configmap = "kubectl get configmap -n ${namespace} ${name} -o json 2>/dev/null || echo '{}'"
  $configmap = generate('/bin/sh', '-c', $kubectl_get_configmap).parsejson

  $kubectl_get_secret = "kubectl get secret -n ${namespace} ${name} -o json 2>/dev/null || echo '{}'"
  $secret = generate('/bin/sh', '-c', $kubectl_get_secret).parsejson

  if $configmap['data'] and $secret['data'] {
    $configmap['data'] + $secret['data'].reduce({}) |$memo, $kv| {
      $memo + { $kv[0] => base64('decode', $kv[1]) }
    }
  }
}
