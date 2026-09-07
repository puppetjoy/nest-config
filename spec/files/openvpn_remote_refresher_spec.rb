# frozen_string_literal: true

require 'tmpdir'

require_relative '../../files/openvpn/refresh-remotes'

RSpec.describe OpenvpnRemoteRefresher do
  let(:host) { 'nest-ext.example.com' }
  let(:resolvers) { ['192.0.2.1', '192.0.2.2', '192.0.2.3'] }

  def refresher(output:, answers:, restarts: [])
    resolver = ->(server, queried_host, _timeout) do
      expect(queried_host).to eq(host)
      value = answers.fetch(server)
      raise value if value.is_a?(Exception)

      value
    end

    described_class.new(
      hosts: [host],
      output: output,
      resolvers: resolvers,
      resolver: resolver,
      restarter: ->(service) { restarts << service },
    )
  end

  it 'atomically adopts a public address agreed by two resolvers and restarts once' do
    Dir.mktmpdir('openvpn-remotes') do |directory|
      output = File.join(directory, 'remotes.conf')
      restarts = []
      answers = {
        '192.0.2.1' => ['173.73.235.215'],
        '192.0.2.2' => ['173.73.235.215'],
        '192.0.2.3' => ['173.73.235.216'],
      }

      result = refresher(output: output, answers: answers, restarts: restarts).refresh(restart_service: 'openvpn-client@nest.service')

      expect(result).to eq(:changed)
      expect(File.read(output)).to include("remote 173.73.235.215 1194\n")
      expect(File.read(output)).not_to include('173.73.235.216')
      expect(restarts).to eq(['openvpn-client@nest.service'])
      expect(File.stat(output).mode & 0o777).to eq(0o644)
    end
  end

  it 'does not restart when the agreed address is already current' do
    Dir.mktmpdir('openvpn-remotes') do |directory|
      output = File.join(directory, 'remotes.conf')
      answers = resolvers.to_h { |server| [server, ['173.73.235.215']] }
      instance = refresher(output: output, answers: answers)

      expect(instance.refresh).to eq(:changed)
      expect(instance.refresh(restart_service: 'openvpn-client@nest.service')).to eq(:unchanged)
    end
  end

  it 'preserves the last-known-good configuration when public DNS is unavailable' do
    Dir.mktmpdir('openvpn-remotes') do |directory|
      output = File.join(directory, 'remotes.conf')
      File.write(output, "remote 198.18.0.1 1194\n")
      answers = resolvers.to_h { |server| [server, Resolv::ResolvTimeout.new] }

      expect(refresher(output: output, answers: answers).refresh).to eq(:unavailable)
      expect(File.read(output)).to eq("remote 198.18.0.1 1194\n")
    end
  end

  it 'preserves the last-known-good configuration while public resolvers disagree' do
    Dir.mktmpdir('openvpn-remotes') do |directory|
      output = File.join(directory, 'remotes.conf')
      File.write(output, "remote 203.0.113.1 1194\n")
      answers = {
        '192.0.2.1' => ['173.73.235.215'],
        '192.0.2.2' => ['173.73.235.216'],
        '192.0.2.3' => [],
      }

      expect(refresher(output: output, answers: answers).refresh).to eq(:unavailable)
      expect(File.read(output)).to eq("remote 203.0.113.1 1194\n")
    end
  end

  it 'rejects private and reserved answers even when resolvers agree' do
    Dir.mktmpdir('openvpn-remotes') do |directory|
      output = File.join(directory, 'remotes.conf')
      File.write(output, "remote 173.73.235.215 1194\n")
      answers = resolvers.to_h { |server| [server, ['172.22.1.11', '203.0.113.8']] }

      expect(refresher(output: output, answers: answers).refresh).to eq(:unavailable)
      expect(File.read(output)).to eq("remote 173.73.235.215 1194\n")
    end
  end
end
