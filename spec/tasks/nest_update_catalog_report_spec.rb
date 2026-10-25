require 'spec_helper'
require 'puppet/transaction/report'
require 'tmpdir'
require_relative '../../tasks/update_catalog_report'

RSpec.describe NestUpdateCatalogReport do
  let(:uuid) { '11111111-1111-4111-8111-111111111111' }
  let(:expected) do
    { 'hostname' => 'fixture', 'certname' => 'fixture.nest', 'boot_id' => uuid,
      'configuration_version' => 'a' * 40, 'transaction_uuid' => uuid, 'status' => 'unchanged',
      'not_before' => 1_790_000_000, 'not_after' => 1_790_000_100 }
  end
  let(:report) do
    value = Puppet::Transaction::Report.new('apply')
    { host: 'fixture.nest', time: Time.at(1_790_000_050).utc, configuration_version: 'a' * 40,
      transaction_uuid: uuid, catalog_uuid: uuid, status: 'unchanged', environment: 'main',
      noop: false, transaction_completed: true, cached_catalog_status: 'not_used' }.each do |key, field|
      value.instance_variable_set("@#{key}", field)
    end
    value
  end
  let(:raw) { report.to_yaml }

  def collect(reader: ->(_path) { raw }, boot: -> { uuid })
    described_class.collect(expected, path: 'fixture-only', certname: 'fixture.nest', hostname: 'fixture', boot: boot, reader: reader)
  end

  it 'binds actual native Puppet YAML without loading objects or exposing resource/log data' do
    expect(Psych).not_to receive(:unsafe_load)
    expect(Psych).not_to receive(:safe_load)
    result = collect
    expect(result).to include('result' => 'pass', 'boot_id' => uuid, 'acceptance_recorded' => false)
    expect(result['report']).to include('configuration_version' => 'a' * 40, 'report_sha256' => Digest::SHA256.hexdigest(raw))
    expect(result['report'].keys).to match_array(described_class::FIELDS + ['report_sha256'])
  end

  { host: 'other.nest', environment: 'test', configuration_version: 'a' * 8,
    transaction_uuid: '22222222-2222-4222-8222-222222222222', catalog_uuid: 'unknown',
    noop: true, transaction_completed: false, status: 'failed', cached_catalog_status: 'on_failure',
    time: Time.at(1_790_000_101).utc }.each do |field, wrong|
    it "refuses wrong or incomplete native #{field}" do
      report.instance_variable_set("@#{field}", wrong)
      expect { collect }.to raise_error(described_class::Unavailable)
    end
  end

  it 'refuses an old report even if its source and transaction match' do
    report.instance_variable_set('@time', Time.at(1_789_999_999).utc)
    expect { collect }.to raise_error(described_class::Unavailable)
  end

  it 'binds the actual native catalog code ID only when independently expected' do
    expected['code_id'] = "sha256:#{'c' * 64}"
    report.code_id = expected['code_id']
    expect(collect['report']['code_id']).to eq(expected['code_id'])
    expect(collect['acceptance_recorded']).to be(false)
    expected.delete('code_id')
    expect(collect['report']).not_to have_key('code_id')
  end

  [nil, '', 'a' * 40, "sha256:#{'d' * 64}"].each do |code_id|
    it "refuses a missing or different expected native code ID #{code_id.inspect}" do
      expected['code_id'] = "sha256:#{'c' * 64}"
      report.code_id = code_id
      expect { collect }.to raise_error(described_class::Unavailable)
    end
  end

  [nil, false, 7, '', 'c' * 64, "sha256:#{'C' * 64}"].each do |code_id|
    it "refuses invalid code ID expectation #{code_id.inspect} before reading" do
      expected['code_id'] = code_id
      expect { collect(reader: ->(_path) { raise 'must not read' }) }.to raise_error(described_class::Unavailable)
    end
  end

  it 'refuses absent, duplicate, aliased, anchored, object-tagged and collection code IDs' do
    expected['code_id'] = "sha256:#{'c' * 64}"
    report.code_id = expected['code_id']
    missing = raw.lines.reject { |line| line.start_with?('code_id:') }.join
    invalid = [missing, raw + "code_id: #{expected['code_id']}\n"]
    ['*missing', "&code #{expected['code_id']}", "!ruby/object:Other #{expected['code_id']}", '[]', '{}'].each do |replacement|
      invalid << missing + "code_id: #{replacement}\n"
    end
    invalid.each { |yaml| expect { described_class.bind(yaml, expected) }.to raise_error(described_class::Unavailable) }
  end

  it 'distinguishes changed from unchanged without accepting either' do
    report.instance_variable_set('@status', 'changed')
    expect { collect }.to raise_error(described_class::Unavailable)
    expected['status'] = 'changed'
    expect(collect).to include('result' => 'pass', 'acceptance_recorded' => false)
  end

  it 'rejects report replacement between observations' do
    reads = [raw, raw + "\n"]
    expect { collect(reader: ->(_path) { reads.shift }) }.to raise_error(described_class::Unavailable)
  end

  it 'rejects a boot change during collection' do
    boots = [uuid, '22222222-2222-4222-8222-222222222222']
    expect { collect(boot: -> { boots.shift }) }.to raise_error(described_class::Unavailable)
  end

  it 'rejects a boot mismatch before reading a report' do
    expect { collect(boot: -> { '22222222-2222-4222-8222-222222222222' }, reader: ->(_path) { raise 'must not read' }) }.to raise_error(described_class::Unavailable)
  end

  ['--- {}', "--- []\n", "--- !ruby/object:Other\nnoop: false\n"].each do |invalid|
    it "rejects an unsupported YAML report shape #{invalid.inspect}" do
      expect { described_class.bind(invalid, expected) }.to raise_error(described_class::Unavailable)
    end
  end

  it 'rejects multiple YAML documents and duplicate top-level keys' do
    expect { described_class.bind(raw + "--- {}\n", expected) }.to raise_error(described_class::Unavailable)
    expect { described_class.bind(raw + "host: fixture.nest\n", expected) }.to raise_error(described_class::Unavailable)
  end

  it 'rejects aliases for selected fields without dereferencing them' do
    expect { described_class.bind(raw.sub('noop: false', 'noop: *missing'), expected) }.to raise_error(described_class::Unavailable)
  end

  it 'does not interpret a quoted false string as a native boolean' do
    expect { described_class.bind(raw.sub('noop: false', 'noop: "false"'), expected) }.to raise_error(described_class::Unavailable)
  end

  it 'rejects missing native completion evidence' do
    expect { described_class.bind(raw.sub("transaction_completed: true\n", ''), expected) }.to raise_error(described_class::Unavailable)
  end

  it 'rejects invalid expectations before invoking readers' do
    expected['configuration_version'] = 'a' * 8
    expect { collect(reader: ->(_path) { raise 'must not read' }) }.to raise_error(described_class::Unavailable)
  end

  it 'rejects unbounded or inverted invocation windows' do
    expected['not_after'] = expected['not_before'] + 86_401
    expect { collect }.to raise_error(described_class::Unavailable)
    expected['not_after'] = expected['not_before'] - 1
    expect { collect }.to raise_error(described_class::Unavailable)
  end

  it 'uses a complete Git configuration version, not an ambiguous abbreviation' do
    setting = File.read(File.expand_path('../../environment.conf', __dir__))
    expect(setting).to include('rev-parse HEAD')
    expect(setting).not_to include('--short')
  end

  it 'reads an owned private regular file only as root' do
    Dir.mktmpdir('catalog-report-') do |dir|
      path = File.join(dir, 'report.yaml')
      File.write(path, raw, mode: 'w', perm: 0o600)
      if Process.euid.zero?
        expect(described_class.read_report(path)).to eq(raw)
      else
        expect { described_class.read_report(path) }.to raise_error(described_class::Unavailable)
      end
    end
  end

  it 'rejects a writable report and a non-regular path' do
    Dir.mktmpdir('catalog-report-') do |dir|
      path = File.join(dir, 'report.yaml')
      File.write(path, raw)
      File.chmod(0o666, path)
      expect { described_class.read_report(path) }.to raise_error(described_class::Unavailable)
      expect { described_class.read_report(dir) }.to raise_error(described_class::Unavailable)
    end
  end

  it 'refuses symbolic links before reading their target' do
    Dir.mktmpdir('catalog-report-') do |dir|
      path = File.join(dir, 'link.yaml')
      File.symlink('missing.yaml', path)
      expect { described_class.read_report(path) }.to raise_error(Errno::ELOOP)
    end
  end
end
