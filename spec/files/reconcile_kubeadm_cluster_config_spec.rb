# frozen_string_literal: true

require 'open3'
require 'rbconfig'
require 'tmpdir'
require 'yaml'

RSpec.describe 'reconcile-kubeadm-cluster-config' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:script) { File.join(repo_root, 'files/kubernetes/reconcile-kubeadm-cluster-config.rb') }
  let(:endpoints) { ['https://172.22.4.9:2379', 'https://172.22.4.8:2379'] }

  def transform(config, *arguments)
    Open3.capture3(RbConfig.ruby, script, *arguments, stdin_data: YAML.dump(config))
  end

  shared_examples 'a v1beta3 transformer' do |extra_args|
    it "writes v1beta3 #{extra_args.is_a?(Hash) ? 'populated' : 'absent/null'} extraArgs as a map" do
      api_server = (extra_args == :absent) ? {} : { 'extraArgs' => extra_args }
      stdout, stderr, status = transform(
        {
          'apiVersion' => 'kubeadm.k8s.io/v1beta3',
          'kind' => 'ClusterConfiguration',
          'apiServer' => api_server,
        },
        *endpoints,
      )

      expect(stderr).to be_empty
      expect(status).to be_success
      args = YAML.safe_load(stdout).dig('apiServer', 'extraArgs')
      expect(args['etcd-count-metric-poll-period']).to eq('0')
      expect(args['etcd-servers']).to eq(endpoints.join(','))
      expect(args['feature-gates'].split(',')).to include('SizeBasedListCostEstimate=false')
      expect(args['feature-gates'].split(',')).to include('WatchList=true') if extra_args.is_a?(Hash)
      expect(args['audit-log-maxage']).to eq('7') if extra_args.is_a?(Hash)
    end
  end

  include_examples 'a v1beta3 transformer', :absent
  include_examples 'a v1beta3 transformer', nil
  include_examples 'a v1beta3 transformer', {
    'audit-log-maxage' => '7',
    'etcd-servers' => 'https://old:2379',
    'feature-gates' => 'WatchList=true,SizeBasedListCostEstimate=true',
  }

  shared_examples 'a v1beta4 transformer' do |extra_args|
    it "writes v1beta4 #{extra_args.is_a?(Array) ? 'populated' : 'absent/null'} extraArgs as an ordered argument list" do
      api_server = (extra_args == :absent) ? {} : { 'extraArgs' => extra_args }
      stdout, stderr, status = transform(
        {
          'apiVersion' => 'kubeadm.k8s.io/v1beta4',
          'kind' => 'ClusterConfiguration',
          'apiServer' => api_server,
        },
        *endpoints,
      )

      expect(stderr).to be_empty
      expect(status).to be_success
      args = YAML.safe_load(stdout).dig('apiServer', 'extraArgs')
      expect(args.count { |arg| arg['name'] == 'etcd-count-metric-poll-period' }).to eq(1)
      expect(args).to include({ 'name' => 'etcd-count-metric-poll-period', 'value' => '0' })
      expect(args.count { |arg| arg['name'] == 'etcd-servers' }).to eq(1)
      expect(args).to include({ 'name' => 'etcd-servers', 'value' => endpoints.join(',') })
      feature_gates = args.find { |arg| arg['name'] == 'feature-gates' }.fetch('value').split(',')
      expect(feature_gates).to include('SizeBasedListCostEstimate=false')
      expect(feature_gates).to include('WatchList=true') if extra_args.is_a?(Array)
      expect(args).to include({ 'name' => 'audit-log-maxage', 'value' => '7' }) if extra_args.is_a?(Array)
    end
  end

  include_examples 'a v1beta4 transformer', :absent
  include_examples 'a v1beta4 transformer', nil
  include_examples 'a v1beta4 transformer', [
    { 'name' => 'audit-log-maxage', 'value' => '7' },
    { 'name' => 'etcd-servers', 'value' => 'https://old:2379' },
    { 'name' => 'feature-gates', 'value' => 'WatchList=true,SizeBasedListCostEstimate=true' },
  ]

  it 'fails readback checking when endpoint order or membership differs' do
    config = {
      'apiVersion' => 'kubeadm.k8s.io/v1beta4',
      'kind' => 'ClusterConfiguration',
      'apiServer' => {
        'extraArgs' => [
          { 'name' => 'etcd-count-metric-poll-period', 'value' => '0' },
          { 'name' => 'etcd-servers', 'value' => endpoints.reverse.join(',') },
          { 'name' => 'feature-gates', 'value' => 'SizeBasedListCostEstimate=false' },
        ],
      },
    }
    _stdout, stderr, status = transform(config, '--check', *endpoints)

    expect(status).not_to be_success
    expect(stderr).to include('etcd-servers differs')
  end

  it 'fails readback checking when v1beta4 contains duplicate endpoint arguments' do
    config = {
      'apiVersion' => 'kubeadm.k8s.io/v1beta4',
      'kind' => 'ClusterConfiguration',
      'apiServer' => {
        'extraArgs' => [
          { 'name' => 'etcd-count-metric-poll-period', 'value' => '0' },
          { 'name' => 'etcd-servers', 'value' => endpoints.join(',') },
          { 'name' => 'etcd-servers', 'value' => endpoints.join(',') },
          { 'name' => 'feature-gates', 'value' => 'SizeBasedListCostEstimate=false' },
        ],
      },
    }
    _stdout, stderr, status = transform(config, '--check', *endpoints)

    expect(status).not_to be_success
    expect(stderr).to include('expected exactly one etcd-servers argument, got 2')
  end

  it 'fails readback checking when object-count polling remains enabled' do
    config = {
      'apiVersion' => 'kubeadm.k8s.io/v1beta4',
      'kind' => 'ClusterConfiguration',
      'apiServer' => {
        'extraArgs' => [
          { 'name' => 'etcd-count-metric-poll-period', 'value' => '1m' },
          { 'name' => 'etcd-servers', 'value' => endpoints.join(',') },
          { 'name' => 'feature-gates', 'value' => 'SizeBasedListCostEstimate=false' },
        ],
      },
    }
    _stdout, stderr, status = transform(config, '--check', *endpoints)

    expect(status).not_to be_success
    expect(stderr).to include('etcd-count-metric-poll-period differs')
  end

  it 'fails readback checking when size-based list cost estimation remains enabled' do
    config = {
      'apiVersion' => 'kubeadm.k8s.io/v1beta4',
      'kind' => 'ClusterConfiguration',
      'apiServer' => {
        'extraArgs' => [
          { 'name' => 'etcd-count-metric-poll-period', 'value' => '0' },
          { 'name' => 'etcd-servers', 'value' => endpoints.join(',') },
          { 'name' => 'feature-gates', 'value' => 'WatchList=true,SizeBasedListCostEstimate=true' },
        ],
      },
    }
    _stdout, stderr, status = transform(config, '--check', *endpoints)

    expect(status).not_to be_success
    expect(stderr).to include('feature-gates must disable SizeBasedListCostEstimate')
  end

  it 'compares restored configuration structurally' do
    config = {
      'apiVersion' => 'kubeadm.k8s.io/v1beta4',
      'kind' => 'ClusterConfiguration',
      'apiServer' => { 'extraArgs' => [] },
    }
    backup = File.join(Dir.tmpdir, "kubeadm-config-#{Process.pid}.yaml")
    File.write(backup, YAML.dump(config))

    _stdout, stderr, status = transform(config, '--compare', backup)

    expect(stderr).to be_empty
    expect(status).to be_success
  ensure
    File.delete(backup) if backup && File.exist?(backup)
  end
end
