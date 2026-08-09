#!/usr/bin/env ruby
# frozen_string_literal: true

require 'optparse'
require 'yaml'

mode = :write
comparison_path = nil
parser = OptionParser.new do |options|
  options.on('--check') { mode = :check }
  options.on('--compare FILE') do |path|
    mode = :compare
    comparison_path = path
  end
end
parser.parse!

expected_endpoints = ARGV
raise 'at least one etcd endpoint is required' if mode != :compare && expected_endpoints.empty?

config = YAML.safe_load($stdin.read, permitted_classes: [], permitted_symbols: [], aliases: false)
raise 'input is not a kubeadm ClusterConfiguration' unless config.is_a?(Hash) && config['kind'] == 'ClusterConfiguration'

if mode == :compare
  expected = YAML.safe_load_file(comparison_path, permitted_classes: [], permitted_symbols: [], aliases: false)
  raise 'ClusterConfiguration differs from backup' unless config == expected

  puts comparison_path
  exit
end

api_server = config['apiServer'] ||= {}
default_extra_args = (config['apiVersion'] == 'kubeadm.k8s.io/v1beta4') ? [] : {}
extra_args = api_server['extraArgs'] ||= default_extra_args

case extra_args
when Hash
  actual_endpoints = extra_args['etcd-servers'].to_s.split(',')
  etcd_arg_count = extra_args.key?('etcd-servers') ? 1 : 0
  extra_args['etcd-servers'] = expected_endpoints.join(',') unless mode == :check
when Array
  etcd_args = extra_args.select { |arg| arg['name'] == 'etcd-servers' }
  actual_endpoints = etcd_args.empty? ? [] : etcd_args.first['value'].to_s.split(',')
  etcd_arg_count = etcd_args.length
  unless mode == :check
    extra_args.reject! { |arg| arg['name'] == 'etcd-servers' }
    extra_args << { 'name' => 'etcd-servers', 'value' => expected_endpoints.join(',') }
  end
else
  raise "unsupported apiServer.extraArgs shape: #{extra_args.class}"
end

if mode == :check
  raise "expected exactly one etcd-servers argument, got #{etcd_arg_count}" unless etcd_arg_count == 1
  raise "etcd endpoints differ: expected #{expected_endpoints.inspect}, got #{actual_endpoints.inspect}" unless actual_endpoints == expected_endpoints

  puts expected_endpoints.join(',')
else
  puts YAML.dump(config)
end
