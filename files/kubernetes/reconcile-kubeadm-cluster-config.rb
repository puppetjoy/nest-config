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

feature_gate = 'SizeBasedListCostEstimate'
reconcile_feature_gates = ->(value) {
  gates = value.to_s.split(',').reject(&:empty?)
  gates.reject! { |gate| gate.split('=', 2).first == feature_gate }
  gates << "#{feature_gate}=false"
  gates.join(',')
}

managed_extra_args = {
  'etcd-count-metric-poll-period' => '0',
  'etcd-servers' => expected_endpoints.join(','),
}

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
  actual_managed_args = managed_extra_args.keys.to_h { |name| [name, extra_args[name]] }
  managed_arg_counts = managed_extra_args.keys.to_h { |name| [name, extra_args.key?(name) ? 1 : 0] }
  feature_gate_count = extra_args.key?('feature-gates') ? 1 : 0
  actual_feature_gates = extra_args['feature-gates']
  unless mode == :check
    extra_args.merge!(managed_extra_args)
    extra_args['feature-gates'] = reconcile_feature_gates.call(actual_feature_gates)
  end
when Array
  actual_managed_args = managed_extra_args.keys.to_h do |name|
    args = extra_args.select { |arg| arg['name'] == name }
    [name, args.empty? ? nil : args.first['value']]
  end
  managed_arg_counts = managed_extra_args.keys.to_h do |name|
    [name, extra_args.count { |arg| arg['name'] == name }]
  end
  feature_gate_args = extra_args.select { |arg| arg['name'] == 'feature-gates' }
  feature_gate_count = feature_gate_args.length
  actual_feature_gates = feature_gate_args.first&.fetch('value', nil)
  unless mode == :check
    extra_args.reject! { |arg| managed_extra_args.key?(arg['name']) || arg['name'] == 'feature-gates' }
    managed_extra_args.each { |name, value| extra_args << { 'name' => name, 'value' => value } }
    extra_args << { 'name' => 'feature-gates', 'value' => reconcile_feature_gates.call(actual_feature_gates) }
  end
else
  raise "unsupported apiServer.extraArgs shape: #{extra_args.class}"
end

if mode == :check
  managed_extra_args.each do |name, expected_value|
    count = managed_arg_counts.fetch(name)
    raise "expected exactly one #{name} argument, got #{count}" unless count == 1

    actual_value = actual_managed_args.fetch(name)
    raise "#{name} differs: expected #{expected_value.inspect}, got #{actual_value.inspect}" unless actual_value == expected_value
  end

  raise "expected exactly one feature-gates argument, got #{feature_gate_count}" unless feature_gate_count == 1

  feature_gates = actual_feature_gates.to_s.split(',')
  unless feature_gates.include?("#{feature_gate}=false")
    raise "feature-gates must disable #{feature_gate}: got #{actual_feature_gates.inspect}"
  end

  puts expected_endpoints.join(',')
else
  puts YAML.dump(config)
end
