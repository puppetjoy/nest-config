require 'spec_helper'

RSpec.describe 'Kubernetes config image references' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:common_yaml) { File.read(File.join(repo_root, 'data/kubernetes/common.yaml')) }
  let(:test_yaml) { File.read(File.join(repo_root, 'data/kubernetes/test.yaml')) }
  let(:honcho_yaml) { File.read(File.join(repo_root, 'data/kubernetes/app/honcho.yaml')) }
  let(:monitoring_yaml) { File.read(File.join(repo_root, 'data/kubernetes/app/kube-prometheus-stack.yaml')) }
  let(:monitoring_values) { YAML.safe_load(monitoring_yaml, aliases: true).fetch('values').fetch('kube-state-metrics') }
  let(:registry_yaml) { File.read(File.join(repo_root, 'data/kubernetes/service/registry.yaml')) }
  let(:ci_yaml) { File.read(File.join(repo_root, '.gitlab-ci.yml')) }

  it 'defines the Nest config image with an explicit tag' do
    expect(common_yaml).to include(%(config_image: "%{lookup('config_registry')}/nest/config/main:latest"))
  end

  it 'uses the tagged config image alias for the shared backup CronJob' do
    expect(common_yaml).to match(%r{kind: CronJob.*image: "%\{lookup\('config_image'\)\}"}m)
    expect(common_yaml).not_to include(%(image: "%{lookup('config_registry')}/nest/config/main"))
  end

  it 'bounds shared backup jobs so image pull stalls cannot block future schedules' do
    expect(common_yaml).to include('backup_job_active_deadline_seconds: 7200')
    expect(common_yaml).to include(%(activeDeadlineSeconds: "%{alias('backup_job_active_deadline_seconds')}"))
  end

  it 'keeps Honcho backups on the Nest config image path with a tighter pull deadline' do
    expect(honcho_yaml).to include('backup_job_active_deadline_seconds: 1800')
    expect(honcho_yaml).not_to match(%r{^  backup:\n    apiVersion:})
  end

  it 'allows full registry backups to exceed two hours without overlapping the next schedule' do
    expect(registry_yaml).to include('backup_job_active_deadline_seconds: 9900')
    expect(registry_yaml).to include("backup_schedule: '0 2-23/3 * * *'")
    expect(registry_yaml).to include("restore_schedule: '35 3-23/3 * * *'")
    expect(registry_yaml).to include('restore_job_active_deadline_seconds: 9900')
  end

  it 'bounds restores and allows services to override complete backup and restore schedules' do
    expect(common_yaml).to include(%(schedule: "%{lookup('backup_schedule')}"))
    expect(test_yaml).to include('restore_job_active_deadline_seconds: 7200')
    expect(test_yaml).to include(%(activeDeadlineSeconds: "%{alias('restore_job_active_deadline_seconds')}"))
    expect(test_yaml).to include(%(schedule: "%{lookup('restore_schedule')}"))
  end

  it 'keeps kube-state-metrics from listing Secret payloads cluster-wide' do
    collectors = monitoring_values.fetch('collectors')

    expect(collectors).to eq(
      [
        'certificatesigningrequests', 'configmaps', 'cronjobs', 'daemonsets',
        'deployments', 'endpoints', 'endpointslices', 'horizontalpodautoscalers',
        'ingresses', 'jobs', 'leases', 'limitranges',
        'mutatingwebhookconfigurations', 'namespaces', 'networkpolicies', 'nodes',
        'persistentvolumeclaims', 'persistentvolumes', 'poddisruptionbudgets', 'pods',
        'replicasets', 'replicationcontrollers', 'resourcequotas', 'services',
        'statefulsets', 'storageclasses', 'validatingwebhookconfigurations',
        'volumeattachments'
      ],
    )
  end

  it 'uses the tagged config image alias for Honcho init jobs' do
    expect(honcho_yaml).to include(%(image: "%{lookup('config_image')}"))
    expect(honcho_yaml).not_to include(%(image: "%{lookup('config_registry')}/nest/config/main"))
  end

  it 'publishes the config manifest with the explicit latest tag used by jobs' do
    expect(ci_yaml).to include('"${CI_REGISTRY}/${IMAGE}:latest"')
    expect(ci_yaml).to include('"registry.eyrie/${IMAGE}:latest"')
  end
end
