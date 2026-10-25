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

  def collect(reader: ->(_path) { raw }, boot: -> { uuid })
    described_class.collect(expected, path: 'fixture-only', certname: 'fixture.nest', server: 'puppet.eyrie',
                            hostname: 'fixture', boot: boot, reader: reader, clock: -> { 1_790_000_000 })
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
    expect { described_class.read_cache('/proc/self/fd/0') }.to raise_error(Errno::ELOOP)
    expect { described_class.read_cache('/') }.to raise_error(NestUpdateCatalogReport::Unavailable)
    expect { described_class.read_cache('relative') }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end
end
