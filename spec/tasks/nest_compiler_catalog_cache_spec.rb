require 'spec_helper'
require_relative '../../tasks/compiler_catalog_cache'

RSpec.describe NestCompilerCatalogCache do
  let(:uuid) { '11111111-1111-4111-8111-111111111111' }
  let(:expected) { { 'hostname' => 'fixture', 'certname' => 'fixture.nest', 'server' => 'puppet.eyrie' } }
  let(:catalog) do
    { 'name' => 'fixture.nest', 'environment' => 'main', 'version' => 'a' * 40, 'code_id' => nil,
      'catalog_uuid' => uuid, 'resources' => [{ 'type' => 'Notify', 'title' => 'private-payload' }] }
  end
  let(:raw) { JSON.generate(catalog) }

  def collect(reader: ->(_path) { raw }, boot: -> { uuid }, native_platform: 'linux')
    described_class.collect(expected, path: 'fixture-only', certname: 'fixture.nest', server: 'puppet.eyrie',
                            hostname: 'fixture', boot: boot, reader: reader, clock: -> { 1_790_000_000 }, native_platform: native_platform)
  end

  it 'returns only sanitized native cache identity and an explicit null legacy code ID' do
    result = collect
    expect(result).to include('kind' => 'nest_compiler_catalog_cache', 'read_only' => true, 'catalog_applied' => false, 'acceptance_recorded' => false)
    expect(result['cache']).to eq('configuration_version' => 'a' * 40, 'code_id' => nil, 'catalog_uuid' => uuid, 'cache_sha256' => Digest::SHA256.hexdigest(raw))
    expect(JSON.generate(result)).not_to include('private-payload', 'resources')
  end

  it 'observes a non-null immutable code ID without accepting its source or deploying' do
    catalog['code_id'] = 'sha256:' + ('b' * 64)
    expect(collect['cache']['code_id']).to eq(catalog['code_id'])
  end

  it 'preserves the Linux schema and distinguishes Darwin native uppercase boot sessions' do
    expect(collect['schema']).to eq(1)
    expect(collect).not_to have_key('platform')
    native = '5F573720-AD7D-4CC8-90CB-4FB2520C257A'
    result = collect(boot: -> { native }, native_platform: 'darwin')
    expect(result).to include('schema' => 2, 'platform' => 'darwin', 'boot_source' => 'kern.bootsessionuuid', 'boot_id' => native)
    expect(result['cache']).to eq(collect['cache'])
    expect(JSON.generate(result)).not_to include('private-payload')
  end

  it 'rejects a normalized, malformed, changed or foreign-platform boot identity' do
    native = '5F573720-AD7D-4CC8-90CB-4FB2520C257A'
    [native.downcase, native + "\n", 'unknown', nil].each do |value|
      expect { collect(boot: -> { value }, native_platform: 'darwin') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
    expect { collect(boot: -> { native }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    expect { collect(native_platform: 'cygwin') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    boots = [native, '6F573720-AD7D-4CC8-90CB-4FB2520C257A']
    expect { collect(boot: -> { boots.shift }, native_platform: 'darwin') }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'requires a successful native sysctl record without rewriting its identifier' do
    native = '5F573720-AD7D-4CC8-90CB-4FB2520C257A'
    status = instance_double(Process::Status, success?: true)
    allow(Open3).to receive(:capture3).with('/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid').and_return([native + "\n", '', status])
    expect(described_class.boot_id('darwin')).to eq(native)
    [native, native.downcase + "\n", native + "\n\n", " #{native}\n"].each do |output|
      allow(Open3).to receive(:capture3).and_return([output, '', status])
      expect { described_class.boot_id('darwin') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
    allow(status).to receive(:success?).and_return(false)
    allow(Open3).to receive(:capture3).and_return([native + "\n", 'private-native-error', status])
    expect { described_class.boot_id('darwin') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    expect { described_class.boot_id('windows') }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'preserves historical abbreviated versions only for explicitly null code IDs' do
    ['5b732030', '13c279d6', 'a' * 7, 'a' * 39].each do |version|
      catalog['version'] = version
      expect(collect(reader: ->(_path) { JSON.generate(catalog) })['cache']['configuration_version']).to eq(version)
    end
  end

  it 'never expands a legacy version or accepts an abbreviated immutable source' do
    catalog['code_id'] = 'sha256:' + ('b' * 64)
    ['5b732030', 'a' * 7, 'a' * 39].each do |version|
      catalog['version'] = version
      expect { collect(reader: ->(_path) { JSON.generate(catalog) }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
    catalog['code_id'] = nil
    ['', 'a' * 6, 'a' * 41, 'main', '5b732030-extra', "5b732030\n", '5B732030'].each do |version|
      catalog['version'] = version
      expect { collect(reader: ->(_path) { JSON.generate(catalog) }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
  end

  ['name', 'environment', 'version', 'code_id', 'catalog_uuid', 'resources'].each do |field|
    it "distinguishes missing #{field} from a legitimate null code ID" do
      catalog.delete(field)
      expect { collect }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
  end

  { 'name' => 'other', 'environment' => 'test', 'version' => 'main', 'code_id' => '',
    'catalog_uuid' => 'unknown', 'resources' => [] }.each do |field, value|
    it "rejects an invalid #{field}" do
      catalog[field] = value
      expect { collect }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
  end

  it 'refuses duplicate JSON keys at any depth rather than choosing one' do
    [raw.sub('"code_id":null', '"code_id":null,"code_id":null'),
     raw.sub('"type":"Notify"', '"type":"Notify","type":"Notify"')].each do |payload|
      expect { collect(reader: ->(_path) { payload }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    end
  end

  it 'refuses a replaced cache or changed boot during observation' do
    reads = [raw, raw + "\n"]
    expect { collect(reader: ->(_path) { reads.shift }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
    boots = [uuid, '22222222-2222-4222-8222-222222222222']
    expect { collect(boot: -> { boots.shift }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'refuses host, certname, server and malformed expectation mismatches before reading' do
    ['hostname', 'certname', 'server'].each do |field|
      original = expected[field]
      expected[field] = 'other'
      expect { collect(reader: ->(_path) { raise 'must not read' }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
      expected[field] = original
    end
    expected['extra'] = 'not-allowed'
    expect { collect(reader: ->(_path) { raise 'must not read' }) }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'uses the read-only native cache setting and never invokes an agent application' do
    source = File.read(File.expand_path('../../tasks/compiler_catalog_cache.rb', __dir__))
    expect(source).to include("File.join(Puppet[:client_datadir], 'catalog', certname + '.json')")
    expect(source).not_to include('Process.spawn', 'Puppet::Application', 'system(')
  end

  it 'permits native root-group writable caches but no other writable group or world' do
    stat = Struct.new(:uid, :gid, :mode)
    expect(described_class.owned?(stat.new(0, 0, 0o100660))).to be(true)
    expect(described_class.owned?(stat.new(0, 17, 0o100640))).to be(true)
    [stat.new(0, 17, 0o100660), stat.new(17, 0, 0o100600), stat.new(0, 0, 0o100666)].each do |unsafe|
      expect(described_class.owned?(unsafe)).to be(false)
    end
  end

  it 'refuses a symbolic link and non-regular cache before interpreting its content' do
    expect { described_class.read_cache('/proc/self/fd/0') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    expect { described_class.read_cache('/') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    expect { described_class.read_cache('relative') }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'refuses replacement or metadata changes before open and after the bounded read' do
    stat = Struct.new(:dev, :ino, :size, :mtime, :ctime, :uid, :gid, :mode, :nlink) do
      def file?
        true
      end
    end
    original = stat.new(1, 2, raw.bytesize, 3, 4, 0, 0, 0o100660, 1)
    changed = original.dup
    changed.ino = 5
    file = instance_double(File, stat: original, read: raw)
    allow(File).to receive(:open).with('/fixture', File::RDONLY | File::NOFOLLOW | File::NONBLOCK).and_yield(file)
    allow(File).to receive(:lstat).with('/fixture').and_return(original, changed)
    expect { described_class.read_cache('/fixture') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    allow(File).to receive(:lstat).with('/fixture').and_return(changed)
    expect { described_class.read_cache('/fixture') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    allow(File).to receive(:lstat).with('/fixture').and_return(original)
    changed = original.dup
    changed.mode = 0o100666
    allow(file).to receive(:stat).and_return(original, changed)
    expect { described_class.read_cache('/fixture') }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end
end
