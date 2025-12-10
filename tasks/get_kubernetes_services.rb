#!/usr/bin/env ruby

require 'English'
require 'json'
require_relative '../../ruby_task_helper/files/task_helper.rb'

# Fetch Kubernetes service names and URIs with kubectl
class GetKubernetesServices < TaskHelper
  def task(_opts)
    services = `kubectl get services -A -l 'james.tl/nest in (stage1, puppet)' -o json 2>/dev/null`
    kube_env = ENV['KUBECONFIG']
    kubeconfig_missing = kube_env.nil? || kube_env.strip.empty? || kube_env.split(File::PATH_SEPARATOR).all? { |p| p.strip.empty? || !File.exist?(p) }
    unless $CHILD_STATUS.success?
      # Treat as no targets if kubeconfig is unset or points to non-existent files
      return { value: [] } if kubeconfig_missing
      raise TaskHelper::Error.new(
        'nest/kubectl',
        "kubectl failed with exit #{$CHILD_STATUS.exitstatus}",
        {},
      )
    end
    services = JSON.parse(services)

    targets = services['items'].map { |service|
      if service['spec']['type'] == 'LoadBalancer'
        uri = service['metadata']['labels']['james.tl/fqdn']
        config = {}
      else
        namespace = service['metadata']['namespace']
        jump_namespace = (namespace == 'test') ? 'test' : 'default'
        jump_service = services['items'].find { |s| s['metadata']['name'] == 'jump' && s['metadata']['namespace'] == jump_namespace }
        next nil unless jump_service
        uri = "#{service['metadata']['name']}.#{namespace}.svc.cluster.local"
        config = { ssh: { proxyjump: jump_service['metadata']['labels']['james.tl/fqdn'] } }
      end

      {
        name: service['metadata']['labels']['james.tl/service_name'],
        uri: uri,
        config: config,
      }
    }.compact

    { value: targets }
  end
end

if __FILE__ == $PROGRAM_NAME
  GetKubernetesServices.run
end
