require 'spec_helper'
require 'fileutils'
require 'open3'
require 'tmpdir'
require_relative '../../files/puppet-compiler-snapshot'

RSpec.describe NestPuppetCompilerSnapshot do
  let(:work) { Dir.mktmpdir('compiler-copy-', ENV.fetch('TMPDIR', nil)) }
  let(:source) { File.join(work, 'input') }
  let(:destination) { File.join(work, 'snapshot') }
  let(:revision) { 'a' * 40 }
  let(:configuration) { "modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo #{revision}\n" }
  let(:receipt) { File.join(work, 'expected.json') }
  let(:expected) do
    File.write(File.join(source, 'environment.conf'), configuration)
    value = { 'schema' => 1, 'environment' => 'main', 'source' => revision,
              'code_id' => NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(source)) }
    File.write(File.join(source, 'environment.conf'), 'mutable input configuration')
    value
  end

  around(:each) do |example|
    FileUtils.mkdir_p(File.join(source, 'modules/fixture/files'))
    File.write(File.join(source, 'modules/fixture/files/probe.txt'), "frozen\n")
    File.chmod(0o640, File.join(source, 'modules/fixture/files/probe.txt'))
    example.run
  ensure
    FileUtils.remove_entry(work)
  end

  def prepare(value = expected)
    described_class.prepare(source, destination, value)
  end

  it 'copies independently expected bytes and modes without retaining input hard links' do
    result = prepare
    original = File.join(source, 'modules/fixture/files/probe.txt')
    copy = File.join(destination, 'modules/fixture/files/probe.txt')
    expect(result).to include('copied' => true, 'compiler_attestation' => false, 'compiler_read_only_verified' => false)
    expect(File.stat(copy).ino).not_to eq(File.stat(original).ino)
    expect(File.stat(copy).mode & 0o777).to eq(0o640)
    File.write(original, 'new mutable input')
    expect(File.read(copy)).to eq("frozen\n")
    expect(File.read(File.join(destination, 'environment.conf'))).to eq(configuration)
  end

  it 'excludes Git administration without depending on a mutable checkout identity' do
    value = expected
    FileUtils.mkdir_p(File.join(source, '.git'))
    File.write(File.join(source, '.git/private'), 'not compiler input')
    expect(prepare(value)['code_id']).to eq(value['code_id'])
    expect(File.exist?(File.join(destination, '.git'))).to be(false)
  end

  it 'preserves relative contained static links across relocation' do
    File.symlink('probe.txt', File.join(source, 'modules/fixture/files/link'))
    value = expected
    prepare(value)
    snapshot = NestPuppetVersionedCode::Snapshot.new(destination, value, readonly: ->(_path) { true })
    expect(snapshot.content('main', value['code_id'], 'modules/fixture/files/link', &:read)).to eq("frozen\n")
  end

  it 'refuses absolute input links before allocating the output' do
    File.symlink(File.join(source, 'modules/fixture/files/probe.txt'), File.join(source, 'modules/fixture/files/link'))
    expect { prepare }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.exist?(destination)).to be(false)
  end

  it 'refuses escaping links without allocating the output' do
    value = expected
    File.symlink('/etc/hostname', File.join(source, 'escape'))
    expect { prepare(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.exist?(destination)).to be(false)
  end

  it 'refuses special input files before allocating the output' do
    value = expected
    File.mkfifo(File.join(source, 'fifo'))
    expect { prepare(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.exist?(destination)).to be(false)
  end

  it 'never adopts or replaces an existing output' do
    Dir.mkdir(destination)
    File.write(File.join(destination, 'prior'), 'keep')
    expect { prepare }.to raise_error(Errno::EEXIST)
    expect(File.read(File.join(destination, 'prior'))).to eq('keep')
  end

  it 'refuses symlinked and writable output parents' do
    value = expected
    File.symlink(work, File.join(work, 'alias'))
    expect { described_class.prepare(source, File.join(work, 'alias/snapshot'), value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    File.chmod(0o777, work)
    expect { prepare(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.exist?(destination)).to be(false)
  end

  it 'refuses overlapping source and destination before writing' do
    value = expected
    expect { described_class.prepare(source, File.join(source, 'snapshot'), value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect { described_class.prepare(source, work, value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
  end

  it 'refuses a symlinked environment configuration' do
    value = expected
    File.unlink(File.join(source, 'environment.conf'))
    File.symlink('modules/fixture/files/probe.txt', File.join(source, 'environment.conf'))
    expect { prepare(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.exist?(destination)).to be(false)
  end

  it 'does not mint a new identity when copied source bytes have changed' do
    value = expected
    File.write(File.join(source, 'modules/fixture/files/probe.txt'), 'drift')
    expect { prepare(value) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    expect(File.directory?(destination)).to be(true)
    expect { prepare(value) }.to raise_error(Errno::EEXIST)
  end

  [1.0, true, nil].each do |schema|
    it "refuses invalid schema #{schema.inspect} before writing" do
      expect { prepare(expected.merge('schema' => schema)) }.to raise_error(NestPuppetVersionedCode::Unavailable)
      expect(File.exist?(destination)).to be(false)
    end
  end

  it 'refuses malformed or additional receipt fields before writing' do
    value = expected
    [value.merge('source' => 'main'), value.merge('code_id' => 'sha256:wrong'), value.merge('unexpected' => true), value.merge('environment' => 'test')].each do |invalid|
      expect { prepare(invalid) }.to raise_error(NestPuppetVersionedCode::Unavailable)
    end
    expect(File.exist?(destination)).to be(false)
  end

  it 'executes the real CLI copy contract and emits only the sanitized receipt' do
    File.write(receipt, JSON.generate(expected))
    stdout, stderr, status = Open3.capture3('ruby', File.expand_path('../../files/puppet-compiler-snapshot.rb', __dir__), source, destination, receipt)
    expect(status.exitstatus).to eq(0)
    expect(stderr).to eq('')
    expect(JSON.parse(stdout)).to include('kind' => 'nest_puppet_compiler_snapshot', 'copied' => true)
    expect(stdout).not_to include(source, 'probe.txt', 'mutable input')
  end

  it 'refuses malformed receipt JSON at the real CLI boundary without writing' do
    File.write(receipt, '{broken')
    stdout, stderr, status = Open3.capture3('ruby', File.expand_path('../../files/puppet-compiler-snapshot.rb', __dir__), source, destination, receipt)
    expect(status.exitstatus).to eq(1)
    expect(stdout).to eq('')
    expect(stderr).to eq("Compiler snapshot publication unavailable\n")
    expect(File.exist?(destination)).to be(false)
  end
end
