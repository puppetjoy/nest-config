require 'spec_helper'

describe 'libdir fact' do
  before :each do
    Facter.clear
    allow(Facter).to receive(:value).and_call_original
    allow(Facter).to receive(:value).with(:osfamily).and_return('Gentoo')
    load File.expand_path('../../../lib/facter/libdir.rb', __dir__)
  end

  after :each do
    Facter.clear
  end

  { 'arm' => 'lib', 'amd64' => 'lib64', 'arm64' => 'lib64', 'lp64d' => 'lib64', 'x86' => 'lib32' }.each do |abi, directory|
    it "uses the #{abi} native ABI directory" do
      allow(Facter::Core::Execution).to receive(:execute).with('/usr/bin/portageq envvar DEFAULT_ABI').and_return("#{abi}\n")
      allow(Facter::Core::Execution).to receive(:execute).with("/usr/bin/portageq envvar LIBDIR_#{abi}").and_return("#{directory}\n")
      expect(Facter.value(:libdir)).to eq(directory)
    end
  end

  it 'does not guess lib64 when the native ABI is unavailable' do
    allow(Facter::Core::Execution).to receive(:execute).with('/usr/bin/portageq envvar DEFAULT_ABI').and_return(nil)
    expect(Facter.value(:libdir)).to be_nil
  end

  it 'does not interpolate malformed ABI values into a command' do
    allow(Facter::Core::Execution).to receive(:execute).with('/usr/bin/portageq envvar DEFAULT_ABI').and_return('arm; false')
    expect(Facter.value(:libdir)).to be_nil
  end

  it 'does not accept an invalid library directory' do
    allow(Facter::Core::Execution).to receive(:execute).with('/usr/bin/portageq envvar DEFAULT_ABI').and_return('arm')
    allow(Facter::Core::Execution).to receive(:execute).with('/usr/bin/portageq envvar LIBDIR_arm').and_return('../lib64')
    expect(Facter.value(:libdir)).to be_nil
  end
end
