require 'spec_helper'
require 'fileutils'
require 'tmpdir'
require_relative '../../files/puppet-versioned-code'

RSpec.describe NestPuppetVersionedCode do
  let(:source) { 'a' * 40 }
  let(:root) { Dir.mktmpdir('compiler-snapshot-', ENV.fetch('TMPDIR', nil)) }
  let(:expected) do
    { 'schema' => 1, 'environment' => 'main', 'source' => source,
      'code_id' => described_class.code_id(described_class.inventory(root)) }
  end

  around(:each) do |example|
    FileUtils.mkdir_p(File.join(root, 'modules/fixture/files'))
    File.write(File.join(root, 'modules/fixture/files/probe.txt'), "frozen\n")
    File.write(File.join(root, 'environment.conf'), "modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo #{source}\n")
    example.run
  ensure
    FileUtils.remove_entry(root)
  end

  def snapshot(value = expected, readonly: ->(_path) { true })
    described_class::Snapshot.new(root, value, readonly: readonly)
  end

  it 'returns the independently expected exact tree identity for main' do
    expect(snapshot.id('main')).to eq(expected['code_id'])
  end

  it 'streams only exact native module static content' do
    result = snapshot.content('main', expected['code_id'], 'modules/fixture/files/probe.txt', &:read)
    expect(result).to eq("frozen\n")
  end

  it 'refuses a writable compiler tree before inventory' do
    expect(described_class).not_to receive(:inventory)
    expect { snapshot({}, readonly: ->(_path) { false }) }.to raise_error(described_class::Unavailable)
  end

  it 'refuses changed bytes rather than minting a replacement ID' do
    original = expected
    File.write(File.join(root, 'modules/fixture/files/probe.txt'), 'changed')
    expect { snapshot(original) }.to raise_error(described_class::Unavailable)
  end

  it 'binds executable modes as well as bytes' do
    original = expected
    File.chmod(0o700, File.join(root, 'modules/fixture/files/probe.txt'))
    expect { snapshot(original) }.to raise_error(described_class::Unavailable)
  end

  it 'refuses a different source even with the same expected tree' do
    expect { snapshot(expected.merge('source' => 'b' * 40)) }.to raise_error(described_class::Unavailable)
  end

  it 'refuses mutable configuration-version commands and external module paths' do
    ['config_version = git rev-parse HEAD', 'modulepath = /mutable/modules'].each do |line|
      File.write(File.join(root, 'environment.conf'), line + "\n")
      expect { snapshot }.to raise_error(described_class::Unavailable)
    end
  end

  it 'refuses unknown environments and stale identities' do
    expect { snapshot.id('other') }.to raise_error(described_class::Unavailable)
    expect { snapshot.content('main', 'sha256:wrong', 'modules/fixture/files/probe.txt') {} }.to raise_error(described_class::Unavailable)
  end

  ['../environment.conf', 'modules/fixture/files/../../environment.conf', 'modules/fixture/files//probe.txt',
   'modules/fixture/files/./probe.txt', 'data/private.eyaml', '.git/config', 'manifests/site.pp'].each do |path|
    it "refuses content outside the native static boundary: #{path}" do
      expect { snapshot.content('main', expected['code_id'], path) {} }.to raise_error(described_class::Unavailable)
    end
  end

  it 'refuses symlinks escaping the compiler snapshot' do
    File.symlink('/etc/hostname', File.join(root, 'modules/fixture/files/escape'))
    expect { described_class.inventory(root) }.to raise_error(described_class::Unavailable)
  end

  it 'binds a contained missing leaf without treating it as available static content' do
    File.symlink('absent', File.join(root, 'modules/fixture/files/missing'))
    value = expected
    expect(snapshot(value).id('main')).to eq(value['code_id'])
    expect { snapshot(value).content('main', value['code_id'], 'modules/fixture/files/missing') {} }.to raise_error(Errno::ENOENT)
  end

  it 'refuses a dangling link through an escaping parent link' do
    File.symlink('/etc', File.join(root, 'modules/fixture/files/outside'))
    File.symlink('outside/absent', File.join(root, 'modules/fixture/files/missing'))
    expect { described_class.inventory(root) }.to raise_error(described_class::Unavailable)
  end

  it 'refuses a dangling leaf directly outside the snapshot' do
    File.symlink('/nonexistent-compiler-fixture-leaf', File.join(root, 'modules/fixture/files/missing'))
    expect { described_class.inventory(root) }.to raise_error(described_class::Unavailable)
  end

  it 'refuses symlinks from a static directory into private snapshot data' do
    File.write(File.join(root, 'private'), 'not static content')
    File.symlink('../../../private', File.join(root, 'modules/fixture/files/escape'))
    expect { snapshot.content('main', expected['code_id'], 'modules/fixture/files/escape') {} }.to raise_error(described_class::Unavailable)
  end

  it 'uses the most specific mount and exact path boundaries' do
    mounts = "1 0 0:1 / / ro - overlay overlay ro\n2 1 0:2 / /release rw - tmpfs tmpfs rw\n3 2 0:3 / /release/frozen ro - tmpfs tmpfs rw\n"
    expect(described_class.read_only?('/release/frozen/main', mounts)).to be(true)
    expect(described_class.read_only?('/release/frozen-other/main', mounts)).to be(false)
    expect(described_class.read_only?('/release/mutable/main', mounts)).to be(false)
    expect(described_class.read_only?('/release/main', '')).to be(false)
  end
end
