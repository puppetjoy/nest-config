require 'spec_helper'

RSpec.describe 'Kubernetes config image references' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:common_yaml) { File.read(File.join(repo_root, 'data/kubernetes/common.yaml')) }
  let(:test_yaml) { File.read(File.join(repo_root, 'data/kubernetes/test.yaml')) }
  let(:hermes_dashboard_yaml) { File.read(File.join(repo_root, 'data/kubernetes/app/hermes-dashboard.yaml')) }
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

  it 'lets recurring config-image durability jobs start from a cached image during registry outages' do
    durability_job_yamls = [common_yaml, test_yaml, hermes_dashboard_yaml]

    expect(durability_job_yamls).to all(match(%r{kind: CronJob.*image: "%\{lookup\('config_image'\)\}"\n\s+imagePullPolicy: IfNotPresent}m))
  end

  it 'bounds Hermes profile backups when the config image cannot be pulled or found in cache' do
    expect(hermes_dashboard_yaml).to match(
      %r{kind: CronJob.*activeDeadlineSeconds: "%\{alias\('backup_job_active_deadline_seconds'\)\}".*imagePullPolicy: IfNotPresent}m,
    )
  end

  it 'bounds shared backup jobs so image pull stalls cannot block future schedules' do
    expect(common_yaml).to include('backup_job_active_deadline_seconds: 7200')
    expect(common_yaml).to include(%(activeDeadlineSeconds: "%{alias('backup_job_active_deadline_seconds')}"))
  end

  it 'keeps Honcho backups on the Nest config image path with a tighter pull deadline' do
    expect(honcho_yaml).to include('backup_job_active_deadline_seconds: 1800')
    expect(honcho_yaml).not_to match(%r{^  backup:\n    apiVersion:})
  end

  it 'gives registry backup and restore separate nonoverlapping maximum windows' do
    registry = YAML.safe_load(registry_yaml)
    backup_deadline_minutes = registry.fetch('backup_job_active_deadline_seconds') / 60
    restore_deadline_minutes = registry.fetch('restore_job_active_deadline_seconds') / 60
    expand_hours = ->(schedule) do
      range, step = schedule.split[1].split('/')
      first, last = range.split('-').map(&:to_i)
      (first..last).step(step.to_i).to_a
    end

    expect(registry.fetch('backup_schedule')).to eq('0 2-20/6 * * *')
    expect(registry.fetch('restore_schedule')).to eq('0 5-23/6 * * *')
    expect(backup_deadline_minutes).to eq(165)
    expect(restore_deadline_minutes).to eq(165)

    events = expand_hours.call(registry.fetch('backup_schedule')).map { |hour| [hour * 60, backup_deadline_minutes] }
    events += expand_hours.call(registry.fetch('restore_schedule')).map { |hour| [hour * 60, restore_deadline_minutes] }
    events.sort_by!(&:first)
    windows = events.each_with_index.map do |(start, deadline), index|
      next_start = events[(index + 1) % events.length].first
      next_start += 24 * 60 if index == events.length - 1
      [deadline, next_start - start]
    end

    expect(windows).to all(satisfy { |deadline, available| deadline < available })
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
