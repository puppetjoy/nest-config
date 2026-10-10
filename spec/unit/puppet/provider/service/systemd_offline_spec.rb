require 'spec_helper'
require_relative '../../../../../lib/puppet/provider/service/systemd_offline'

describe Puppet::Type.type(:service).provider(:systemd_offline) do
  let(:resource) { Puppet::Type.type(:service).new(name: 'nest-test', provider: :systemd_offline, enable: true) }
  let(:provider) { resource.provider }

  before :each do
    allow(described_class).to receive(:suitable?).and_return(true)
  end

  it 'uses filesystem mode for enablement and unmasking' do
    expect(provider).to receive(:execute).with(['/usr/bin/systemctl', '--root=/', :unmask, '--', 'nest-test']).ordered
    expect(provider).to receive(:execute).with(['/usr/bin/systemctl', '--root=/', :enable, '--', 'nest-test']).ordered
    provider.enable
  end

  it 'uses filesystem mode for disablement' do
    expect(provider).to receive(:execute).with(['/usr/bin/systemctl', '--root=/', :disable, '--', 'nest-test'])
    provider.disable
  end

  it 'reads enabled state without contacting the manager' do
    result = Puppet::Util::Execution::ProcessOutput.new('enabled', 0)
    expect(provider).to receive(:execute).with(['/usr/bin/systemctl', '--root=/', 'is-enabled', '--', 'nest-test'], failonfail: false).and_return(result)
    expect(provider.enabled?).to eq(:true)
  end

  it 'preserves static-unit semantics' do
    allow(provider).to receive(:cached_enabled?).and_return(output: 'static', exitcode: 0)
    expect(provider.enabled_insync?(:false)).to be(true)
  end

  it 'preserves indirect-unit semantics' do
    allow(provider).to receive(:cached_enabled?).and_return(output: 'indirect', exitcode: 0)
    expect(provider.enabled?).to eq(:false)
    expect(provider.enabled_insync?(:false)).to be(true)
  end

  it 'preserves masked-unit semantics' do
    resource[:enable] = :mask
    allow(provider).to receive(:cached_enabled?).and_return(output: 'masked', exitcode: 1)
    expect(provider.enabled?).to eq(:mask)
  end

  it 'does not restart on notifications' do
    expect(provider).not_to receive(:execute)
    expect(provider).not_to receive(:restart)
    resource.refresh
  end

  [:start, :stop, :restart].each do |action|
    it "refuses runtime #{action}" do
      expect(provider).not_to receive(:execute)
      expect { provider.public_send(action) }.to raise_error(Puppet::Error, %r{offline container})
    end
  end
end
