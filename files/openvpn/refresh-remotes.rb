#!/usr/bin/env ruby
# frozen_string_literal: true

require 'fileutils'
require 'ipaddr'
require 'optparse'
require 'resolv'
require 'tempfile'

# Maintains a last-known-good OpenVPN remote list from public DNS consensus.
class OpenvpnRemoteRefresher
  DEFAULT_RESOLVERS = ['1.1.1.1', '8.8.8.8', '9.9.9.9'].freeze
  NON_PUBLIC_NETWORKS = [
    '0.0.0.0/8',
    '10.0.0.0/8',
    '100.64.0.0/10',
    '127.0.0.0/8',
    '169.254.0.0/16',
    '172.16.0.0/12',
    '192.0.0.0/24',
    '192.0.2.0/24',
    '192.88.99.0/24',
    '192.168.0.0/16',
    '198.18.0.0/15',
    '198.51.100.0/24',
    '203.0.113.0/24',
    '224.0.0.0/4',
    '240.0.0.0/4',
  ].map { |network| IPAddr.new(network) }.freeze

  def initialize(hosts:, output:, port: 1194, protocol: nil, resolvers: DEFAULT_RESOLVERS, timeout: 3, resolver: nil, restarter: nil)
    @hosts = hosts
    @output = output
    @port = port
    @protocol = protocol
    @resolvers = resolvers
    @timeout = timeout
    @resolver = resolver || method(:query)
    @restarter = restarter || method(:restart)
  end

  def refresh(restart_service: nil)
    answers = @hosts.map { |host| consensus_answers(host) }
    return :unavailable if answers.any?(&:empty?)

    remotes = answers.flatten.map { |address| remote_line(address) }
    remotes.uniq!

    content = ([
      '# Refreshed from independent public DNS; retained when DNS is unavailable.',
    ] + remotes).join("\n") + "\n"
    return :unchanged if File.file?(@output) && File.read(@output) == content

    atomic_write(content)
    @restarter.call(restart_service) if restart_service
    :changed
  end

  private

  def consensus_answers(host)
    answer_sets = @resolvers.each_with_object([]) do |server, sets|
      answers = resolver_answers(server, host)
      sets << answers unless answers.empty?
    end

    grouped = answer_sets.group_by(&:itself)
    consensus = grouped.max_by { |answers, observations| [observations.length, answers.join(' ')] }
    return [] unless consensus && consensus.last.length >= 2

    consensus.first
  end

  def resolver_answers(server, host)
    @resolver.call(server, host, @timeout).select { |address| public_ipv4?(address) }.uniq.sort
  rescue Resolv::ResolvError, Resolv::ResolvTimeout, IOError, SystemCallError
    []
  end

  def query(server, host, timeout)
    dns = Resolv::DNS.new(nameserver_port: [[server, 53]], search: [], ndots: 1)
    dns.timeouts = timeout
    dns.getresources(host, Resolv::DNS::Resource::IN::A).map { |record| record.address.to_s }
  ensure
    dns&.close
  end

  def public_ipv4?(address)
    ip = IPAddr.new(address)
    ip.ipv4? && NON_PUBLIC_NETWORKS.none? { |network| network.include?(ip) }
  rescue IPAddr::InvalidAddressError
    false
  end

  def remote_line(address)
    line = "remote #{address} #{@port}"
    @protocol ? "#{line} #{@protocol}" : line
  end

  def atomic_write(content)
    directory = File.dirname(@output)
    FileUtils.mkdir_p(directory)
    temporary = Tempfile.new([".#{File.basename(@output)}.", '.tmp'], directory)
    begin
      temporary.write(content)
      temporary.flush
      temporary.fsync
      temporary.chmod(0o644)
      temporary.close
      File.rename(temporary.path, @output)
    ensure
      temporary.close! unless temporary.closed? && !File.exist?(temporary.path)
    end
  end

  def restart(service)
    return if system('/usr/bin/systemctl', 'try-restart', service)

    raise "failed to restart #{service}"
  end
end

if $PROGRAM_NAME == __FILE__
  options = {
    hosts: [],
    port: 1194,
    protocol: nil,
    resolvers: [],
    timeout: 3,
  }

  parser = OptionParser.new do |option|
    option.on('--host HOST') { |host| options[:hosts] << host }
    option.on('--output PATH') { |path| options[:output] = path }
    option.on('--port PORT', Integer) { |port| options[:port] = port }
    option.on('--protocol PROTOCOL', ['tcp', 'udp']) { |protocol| options[:protocol] = protocol }
    option.on('--resolver ADDRESS') { |address| options[:resolvers] << address }
    option.on('--timeout SECONDS', Integer) { |seconds| options[:timeout] = seconds }
    option.on('--restart SERVICE') { |service| options[:restart_service] = service }
  end
  parser.parse!

  abort 'at least one --host is required' if options[:hosts].empty?
  abort '--output is required' unless options[:output]
  options[:resolvers] = OpenvpnRemoteRefresher::DEFAULT_RESOLVERS if options[:resolvers].empty?
  abort 'at least two --resolver values are required' if options[:resolvers].length < 2

  result = OpenvpnRemoteRefresher.new(
    hosts: options[:hosts],
    output: options[:output],
    port: options[:port],
    protocol: options[:protocol],
    resolvers: options[:resolvers],
    timeout: options[:timeout],
  ).refresh(restart_service: options[:restart_service])
  puts "OpenVPN remote refresh: #{result}"
end
