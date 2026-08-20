class nest::service::patternkit (
  Sensitive $smoke_token,
) {
  if defined(Class['nest::kubernetes']) {
    $oauth_proxy_script_base64 = base64('encode', file('nest/app/patternkit/oauth_proxy.py'))
    $egress_proxy_script_base64 = base64('encode', file('nest/app/patternkit/egress_proxy.py'))
    $workbench_bridge_script_base64 = base64('encode', file('nest/app/patternkit/workbench_bridge.py'))
    $smoke_test_script_base64 = base64('encode', file('nest/app/patternkit/smoke_test.py'))
    $smoke_token_unwrapped = $smoke_token.unwrap

    notice('Pattern Kit Studio and its isolated workbench are managed by KubeCM')
  }
}
