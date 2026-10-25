require 'spec_helper'
require 'fileutils'
require 'open3'
require 'tmpdir'
require_relative '../../files/puppet-compiler-store'

RSpec.describe NestPuppetCompilerStore do
  let(:work) { Dir.mktmpdir('compiler-store-', ENV.fetch('TMPDIR', nil)) }
  let(:source) { File.join(work, 'input') }
  let(:store) { File.join(work, 'store') }
  let(:revision) { 'a' * 40 }
  let(:static_path) { 'modules/fixture/files/probe.txt' }
  let(:receipt) { File.join(work, 'expected.json') }
  let(:expected) do
    { 'schema' => 1, 'environment' => 'main', 'source' => revision,
      'code_id' => NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(source)) }
  end

  around(:each) do |example|
    FileUtils.mkdir_p(File.join(source, 'modules/fixture/files'))
    File.write(File.join(source, static_path), "original\n")
    File.write(File.join(source, 'environment.conf'), "modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo #{revision}\n")
    Dir.mkdir(store, 0o700)
    example.run
  ensure
    FileUtils.remove_entry(work)
  end

  def publish(value = expected)
    described_class.publish(source, store, value)
  end

  def root(value)
    File.join(described_class.release_path(store, value['code_id']), 'main')
  end

  def content(value)
    described_class.snapshot(store, value['code_id'], readonly: ->(_path) { true }).content('main', value['code_id'], static_path, &:read)
  end

  it 'publishes and reopens the exact supplied expectation without inventing an identity' do
    value = expected
    expect(publish(value)).to include('published' => true, 'code_id' => value['code_id'], 'compiler_attestation' => false)
    expect(JSON.parse(File.read(File.join(File.dirname(root(value)), 'expected.json')))).to eq(value)
    expect(content(value)).to eq("original\n")
    expect(Dir.glob(File.join(store, '*.pending'))).to be_empty
  end

  it 'is idempotent without replacing accepted files or reading new mutable input' do
    value = expected
    publish(value)
    inode = File.stat(File.join(root(value), static_path)).ino
    File.write(File.join(source, static_path), 'later mutable input')
    expect(publish(value)['published']).to be(true)
    expect(File.stat(File.join(root(value), static_path)).ino).to eq(inode)
    expect(content(value)).to eq("original\n")
  end

  it 'retains old static bytes after a second independently expected publication' do
    first = expected
    publish(first)
    File.write(File.join(source, static_path), "second\n")
    second = expected.merge('code_id' => NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(source)))
    publish(second)
    expect(content(first)).to eq("original\n")
    expect(content(second)).to eq("second\n")
    expect(Dir.children(store).reject { |name| name.start_with?('.') }.sort).to eq([first, second].map { |value| value['code_id'].delete_prefix('sha256:') }.sort)
  end

  it 'preserves prior releases and a diagnostic partial tree on failed publication' do
    first = expected
    publish(first)
    wrong = first.merge('code_id' => 'sha256:' + ('b' * 64))
    expect { publish(wrong) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(content(first)).to eq("original\n")
    expect(File.directory?(described_class.release_path(store, wrong['code_id']) + '.pending')).to be(true)
    expect(File.exist?(described_class.release_path(store, wrong['code_id']))).to be(false)
    expect { publish(wrong) }.to raise_error(Errno::EEXIST)
  end

  it 'refuses existing release drift instead of replacing it from current input' do
    value = expected
    publish(value)
    File.write(File.join(root(value), static_path), 'corrupt')
    expect { publish(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.read(File.join(root(value), static_path))).to eq('corrupt')
  end

  it 'refuses a different source receipt for an existing identity' do
    value = expected
    publish(value)
    expect { publish(value.merge('source' => 'b' * 40)) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(content(value)).to eq("original\n")
  end

  it 'refuses a concurrent publisher rather than waiting or stealing its lock' do
    File.open(File.join(store, '.publish.lock'), File::RDWR | File::CREAT, 0o600) do |lock|
      lock.flock(File::LOCK_EX)
      expect { publish }.to raise_error(NestPuppetVersionedCode::Unavailable)
    end
    expect(Dir.children(store)).to eq(['.publish.lock'])
  end

  it 'refuses writable or symlinked stores and a symlinked lock' do
    value = expected
    File.chmod(0o750, store)
    expect { publish(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    File.chmod(0o700, store)
    File.symlink(store, File.join(work, 'alias'))
    expect { described_class.publish(source, File.join(work, 'alias'), value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    File.symlink(receipt, File.join(store, '.publish.lock'))
    expect { publish(value) }.to raise_error(Errno::ELOOP)
  end

  it 'refuses symlinked releases and receipts, and does not follow a mutable root pointer' do
    value = expected
    publish(value)
    directory = File.dirname(root(value))
    File.rename(directory, File.join(work, 'old'))
    File.symlink(File.join(work, 'old'), directory)
    expect { described_class.snapshot(store, value['code_id']) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    File.unlink(directory)
    File.rename(File.join(work, 'old'), directory)
    File.rename(File.join(directory, 'expected.json'), receipt)
    File.symlink(receipt, File.join(directory, 'expected.json'))
    expect { described_class.snapshot(store, value['code_id']) }.to raise_error(Errno::ELOOP)
  end

  it 'rejects malformed or missing static identities before serving anything' do
    [nil, '../main', 'sha256:wrong'].each do |identity|
      expect { described_class.snapshot(store, identity) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    end
    expect { described_class.snapshot(store, 'sha256:' + ('b' * 64)) }.to raise_error(Errno::ENOENT)
  end

  it 'rejects malformed expectations before allocating any pending tree or lock' do
    value = expected
    [value.merge('schema' => 1.0), value.merge('source' => 'main'), value.merge('environment' => 'test'), value.merge('extra' => true)].each do |invalid|
      expect { publish(invalid) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    end
    expect(Dir.children(store)).to be_empty
  end

  it 'executes real publication and refuses static content on a writable mount' do
    File.write(receipt, JSON.generate(expected))
    helper = File.expand_path('../../files/puppet-compiler-store.rb', __dir__)
    stdout, stderr, status = Open3.capture3('ruby', helper, 'publish', source, store, receipt)
    expect(status.exitstatus).to eq(0)
    expect(stderr).to eq('')
    expect(JSON.parse(stdout)).to include('published' => true, 'compiler_attestation' => false)
    stdout, stderr, status = Open3.capture3('ruby', helper, 'content', store, 'main', expected['code_id'], static_path)
    expect(status.exitstatus).to eq(1)
    expect(stdout).to eq('')
    expect(stderr).to eq("Compiler snapshot store unavailable\n")
  end
end
