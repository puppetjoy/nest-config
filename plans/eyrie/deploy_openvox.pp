# Deploy an OpenVox-backed Puppet service
#
# Deploys the prerequisite resources, OpenVox chart, and the standalone
# Puppetboard client certificate needed for full PuppetDB HTTPS access.
#
# @param service    Puppet service to deploy
# @param namespace  Kubernetes namespace
# @param resources  Deploy supporting resources
# @param openvox    Deploy OpenVox
# @param deploy     Run or skip the deployment
# @param init       Deploy initial revision
# @param render_to  Render the template to a file
plan nest::eyrie::deploy_openvox (
  String  $service   = 'puppet',
  String  $namespace = 'default',
  Boolean $resources = false,
  Boolean $openvox   = true,
  Boolean $deploy    = true,
  Boolean $init      = false,
  String  $render_to = '',
) {
  run_plan('nest::kubernetes::deploy', {
    'namespace' => $namespace,
    'service'   => "${service}-resources",
    'app'       => 'openvox-resources',
    'deploy'    => $deploy and $resources or $init,
    'wait'      => $render_to == '',
    'render_to' => $render_to,
  })

  run_plan('nest::kubernetes::deploy', {
    'namespace' => $namespace,
    'service'   => $service,
    'app'       => 'openvox',
    'chart'     => 'openvox/puppetserver',
    'repo_url'  => 'https://openvoxproject.github.io/openvox-helm-chart',
    'version'   => '10.1.1',
    'deploy'    => $deploy and $openvox,
    'init'      => $init,
    'wait'      => $init,
    'render_to' => $render_to,
  })

  if $deploy and $openvox and $render_to == '' {
    $certname    = "${service}-puppetboard.${namespace}.svc"
    $cert_secret = "${service}-puppetboard-puppetdb-client"
    $command     = @("SCRIPT"/$)
      set -euo pipefail

      namespace="\$NAMESPACE"
      service="\$SERVICE"
      certname="\$CERTNAME"
      cert_secret="\$CERT_SECRET"

      kubectl rollout status -n "\$namespace" \
        "deploy/\${service}-puppetserver-puppetserver-master" \
        --timeout=240s

      pod=\$(kubectl get pod -n "\$namespace" \
        -l "app.kubernetes.io/component=puppetserver,app.kubernetes.io/instance=\${service}" \
        --sort-by=.metadata.creationTimestamp \
        -o name | tail -n 1 | cut -d / -f 2)
      container=\$(kubectl get deploy -n "\$namespace" \
        "\${service}-puppetserver-puppetserver-master" \
        -o jsonpath='{.spec.template.spec.containers[0].name}')

      kubectl exec -n "\$namespace" "\$pod" -c "\$container" -- \
        /bin/sh -ec '
          certname="\$1"
          if [ ! -f "/etc/puppetlabs/puppet/ssl/certs/\${certname}.pem" ]; then
            puppetserver ca generate --certname "\$certname"
          fi
        ' sh "\$certname"

      tmp=\$(mktemp -d)
      trap 'rm -rf "\$tmp"' EXIT

      kubectl exec -n "\$namespace" "\$pod" -c "\$container" -- \
        cat /etc/puppetlabs/puppet/ssl/certs/ca.pem > "\$tmp/ca.pem"
      kubectl exec -n "\$namespace" "\$pod" -c "\$container" -- \
        cat "/etc/puppetlabs/puppet/ssl/certs/\${certname}.pem" > "\$tmp/cert.pem"
      kubectl exec -n "\$namespace" "\$pod" -c "\$container" -- \
        cat "/etc/puppetlabs/puppet/ssl/private_keys/\${certname}.pem" > "\$tmp/key.pem"

      kubectl create secret generic "\$cert_secret" -n "\$namespace" \
        --from-file=ca.pem="\$tmp/ca.pem" \
        --from-file=cert.pem="\$tmp/cert.pem" \
        --from-file=key.pem="\$tmp/key.pem" \
        --dry-run=client -o yaml | kubectl apply -f -

      if kubectl get deploy -n "\$namespace" "\${service}-puppetboard" >/dev/null 2>&1; then
        kubectl rollout restart -n "\$namespace" "deploy/\${service}-puppetboard"
      fi
      | SCRIPT

    run_command($command, 'localhost', 'Generate and sync Puppetboard PuppetDB client certificate', '_env_vars' => {
      'CERTNAME'    => $certname,
      'CERT_SECRET' => $cert_secret,
      'NAMESPACE'   => $namespace,
      'SERVICE'     => $service,
    })
  }
}
