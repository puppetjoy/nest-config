require 'spec_helper'
require 'puppet/transaction/report'
require 'tmpdir'
require 'open3'
require_relative '../../tasks/update_catalog_apply'

RSpec.describe NestUpdateCatalogApply do
  let(:boot_id) { '11111111-1111-4111-8111-111111111111' }
  let(:expected) { { 'hostname' => 'fixture', 'certname' => 'fixture.nest', 'boot_id' => boot_id, 'configuration_version' => 'a' * 40 } }
  let(:first_uuid) { '22222222-2222-4222-8222-222222222222' }
  let(:second_uuid) { '33333333-3333-4333-8333-333333333333' }

  def native_report(uuid, status, code_id: nil)
    value = Puppet::Transaction::Report.new('apply')
    value.code_id = code_id
    { host: 'fixture.nest', time: Time.at(1_790_000_050).utc, configuration_version: 'a' * 40,
      transaction_uuid: uuid, catalog_uuid: uuid, status: status, environment: 'main',
      noop: false, transaction_completed: true, cached_catalog_status: 'not_used' }.each do |key, field|
      value.instance_variable_set("@#{key}", field)
    end
    value.to_yaml
  end

  def invoke(exits, reports: nil, boot: -> { boot_id }, reader: ->(path) { File.read(path) })
    seen = []
    output = nil
    Dir.mktmpdir('bound-catalog-spec-') do |dir|
      runner = ->(_wrapper, path, _log) do
        expect(File.exist?(path)).to be(false)
        expect(File.stat(File.dirname(path)).mode & 0o777).to eq(0o700)
        code = exits.fetch(seen.length)
        uuid = seen.empty? ? first_uuid : second_uuid
        status = (code == 2) ? 'changed' : 'unchanged'
        yaml = reports ? reports.fetch(seen.length) : native_report(uuid, status)
        File.write(path, yaml) unless yaml.nil?
        seen << path
        code
      end
      output = described_class.run(expected, state_dir: dir, certname: 'fixture.nest', hostname: 'fixture', boot: boot,
                                   runner: runner, reader: reader, clock: -> { 1_790_000_050.5 })
      expect(Dir.children(dir)).to be_empty
    end
    [output, seen]
  end

  [0, 2].each do |first|
    it "binds native first exit #{first} and the distinct unchanged repeat without acceptance" do
      result, seen = invoke([first, 0])
      expect(result).to include('result' => 'pass', 'converged' => true, 'repeat_attempted' => true,
                               'served_source_verified' => false, 'acceptance_recorded' => false)
      expect(result['main']).to include('native_exit' => first, 'report_bound' => true)
      expect(result['main']['report']['transaction_uuid']).to eq(first_uuid)
      expect(result['repeat']['report']['transaction_uuid']).to eq(second_uuid)
      expect(seen.uniq.length).to eq(2)
      expect(result.to_s).not_to include('resource_statuses', 'logs', 'metrics')
    end
  end

  [1, 4, 6, 37, nil].each do |first|
    it "preserves failed or unknown native first exit #{first.inspect} without a repeat" do
      result, seen = invoke([first])
      expect(result).to include('result' => 'fail', 'converged' => false, 'repeat_attempted' => false)
      expect(result['main']).to eq('native_exit' => first, 'report_bound' => false)
      expect(seen.length).to eq(1)
    end
  end

  [1, 2, 4, 6, 37, nil].each do |second|
    it "never retries nonconverged repeat exit #{second.inspect}" do
      result, seen = invoke([2, second])
      expect(result).to include('result' => 'fail', 'converged' => false, 'repeat_attempted' => true)
      expect(result['repeat']['native_exit']).to eq(second)
      expect(seen.length).to eq(2)
    end
  end

  it 'refuses missing invocation output rather than adopting the shared last report' do
    result, seen = invoke([0], reports: [nil])
    expect(result['main']).to eq('native_exit' => 0, 'report_bound' => false)
    expect(result['result']).to eq('fail')
    expect(seen.length).to eq(1)
  end

  it 'refuses a wrong served source without the second apply' do
    wrong = native_report(first_uuid, 'unchanged').sub('a' * 40, 'b' * 40)
    result, seen = invoke([0], reports: [wrong])
    expect(result['main']).to eq('native_exit' => 0, 'report_bound' => false)
    expect(seen.length).to eq(1)
  end

  it 'binds the same independently expected code ID across both native reports and durable retention' do
    expected['code_id'] = "sha256:#{'c' * 64}"
    reports = [native_report(first_uuid, 'changed', code_id: expected['code_id']),
               native_report(second_uuid, 'unchanged', code_id: expected['code_id'])]
    result, seen = invoke([2, 0], reports: reports)
    expect(result).to include('result' => 'pass', 'converged' => true, 'served_source_verified' => false)
    expect(seen.length).to eq(2)
    Dir.mktmpdir('code-id-retention-') do |dir|
      params = { 'action' => 'retain', 'expectations' => expected, 'transaction' => 'fixture-code-id',
                 'release' => "sha256:#{'b' * 64}", 'output_dir' => dir, 'report' => JSON.generate(result) }
      stdout, stderr, status = Open3.capture3('python3', File.expand_path('../../tasks/retain_update_catalog.py', __dir__), stdin_data: JSON.generate(params))
      expect(status.exitstatus).to eq(0), stderr + stdout
      receipt = JSON.parse(stdout)
      raw = File.read(receipt['path'])
      expect(receipt['sha256']).to eq(Digest::SHA256.hexdigest(raw))
      retained = JSON.parse(raw)
      expect(retained['expectations']).to eq(expected)
      expect(retained['catalog']).to eq(result)
      expect(retained['served_source_verified']).to be(false)
    end
  end

  [nil, "sha256:#{'d' * 64}"].each do |code_id|
    it "stops after an unbound first code ID #{code_id.inspect} without retry or repeat" do
      expected['code_id'] = "sha256:#{'c' * 64}"
      result, seen = invoke([2], reports: [native_report(first_uuid, 'changed', code_id: code_id)])
      expect(result).to include('result' => 'fail', 'repeat_attempted' => false, 'converged' => false)
      expect(result['main']).to eq('native_exit' => 2, 'report_bound' => false)
      expect(seen.length).to eq(1)
    end

    it "refuses an unbound repeat code ID #{code_id.inspect} without a third apply" do
      expected['code_id'] = "sha256:#{'c' * 64}"
      reports = [native_report(first_uuid, 'changed', code_id: expected['code_id']),
                 native_report(second_uuid, 'unchanged', code_id: code_id)]
      result, seen = invoke([2, 0], reports: reports)
      expect(result).to include('result' => 'fail', 'repeat_attempted' => true, 'converged' => false)
      expect(result['repeat']).to eq('native_exit' => 0, 'report_bound' => false)
      expect(seen.length).to eq(2)
    end
  end

  it 'refuses invalid expected code identity before any native apply' do
    expected['code_id'] = 'main'
    expect {
      described_class.run(expected, state_dir: 'not-created', certname: 'fixture.nest', runner: ->(*) { raise 'must not apply' })
    }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'refuses a report whose status contradicts the native detailed exit' do
    result, seen = invoke([2], reports: [native_report(first_uuid, 'unchanged')])
    expect(result['main']['report_bound']).to be(false)
    expect(seen.length).to eq(1)
  end

  it 'refuses duplicate native transactions across the pair' do
    result, = invoke([0, 0], reports: [native_report(first_uuid, 'unchanged')] * 2)
    expect(result).to include('result' => 'fail', 'converged' => false, 'identity_binding_failed' => true)
  end

  it 'stops on a changed boot after the first apply while retaining its known exit' do
    boots = [boot_id, first_uuid]
    result, seen = invoke([0], boot: -> { boots.shift })
    expect(result).to include('result' => 'fail', 'repeat_attempted' => false, 'identity_binding_failed' => true)
    expect(result['main']['native_exit']).to eq(0)
    expect(seen.length).to eq(1)
  end

  it 'refuses invalid initial identity before the runner' do
    expect {
      described_class.run(expected, state_dir: 'not-created', certname: 'other', runner: ->(*) { raise 'must not apply' })
    }.to raise_error(NestUpdateCatalogReport::Unavailable)
  end

  it 'retains the actual native-report producer result through the supervisor stdin task' do
    [0, 2, 4].each do |second|
      result, = invoke([2, second])
      Dir.mktmpdir('retained-catalog-spec-') do |dir|
        params = { 'action' => 'retain', 'expectations' => expected, 'transaction' => 'fixture-cycle',
                   'release' => "sha256:#{'b' * 64}", 'output_dir' => dir, 'report' => JSON.generate(result) }
        stdout, stderr, status = Open3.capture3('python3', File.expand_path('../../tasks/retain_update_catalog.py', __dir__), stdin_data: JSON.generate(params))
        expect(status.exitstatus).to eq(0), stderr + stdout
        receipt = JSON.parse(stdout)
        raw = File.read(receipt['path'])
        expect(receipt['sha256']).to eq(Digest::SHA256.hexdigest(raw))
        expect(receipt['readback_verified']).to be(true)
        document = JSON.parse(raw)
        expect(document['catalog']).to eq(result)
        expect(document).to include('release_binding_verified' => false, 'acceptance_recorded' => false, 'served_source_verified' => false)
      end
    end
  end

  it 'uses argv paths and does not inherit build or extra argument overrides' do
    expect(Process).to receive(:spawn) do |env, shell, wrapper, *args, **options|
      expect(env).to include('PUPPET_EXTRA_ARGS' => '', 'PUPPET_PRESERVE_DETAILED_EXIT' => 'true', 'FACTER_build' => nil, 'FACTER_skip_module_rebuild' => nil)
      expect([shell, wrapper]).to eq(['/bin/sh', '/fixture/wrapper'])
      expect(args).to eq(described_class::ARGS + ['--lastrunreport', '/private path/report', '--lastrunfile', '/private path/report.summary'])
      expect(options).to eq(out: '/private path/log', err: '/private path/log')
      123
    end
    status = instance_double(Process::Status, exitstatus: 2)
    expect(Process).to receive(:wait2).with(123).and_return([123, status])
    expect(described_class.execute('/fixture/wrapper', '/private path/report', '/private path/log')).to eq(2)
  end

  it 'exercises the actual wrapper and process runner with disposable native-report command fakes' do
    Dir.mktmpdir('bound-native-spec-') do |dir|
      File.write(File.join(dir, 'systemctl'), "#!/bin/sh\nexit 1\n", mode: 'w', perm: 0o700)
      fixture = <<~'RUBY'
        #!/usr/bin/env ruby
        require 'puppet'
        require 'puppet/transaction/report'
        path = ARGV.fetch(ARGV.index('--lastrunreport') + 1)
        changed = File.basename(path) == 'main.yaml'
        report = Puppet::Transaction::Report.new('apply')
        uuid = changed ? '22222222-2222-4222-8222-222222222222' : '33333333-3333-4333-8333-333333333333'
        { host: 'fixture.nest', time: Time.now, configuration_version: 'a' * 40,
          transaction_uuid: uuid, catalog_uuid: uuid, status: changed ? 'changed' : 'unchanged', environment: 'main',
          noop: false, transaction_completed: true, cached_catalog_status: 'not_used' }.each do |key, field|
          report.instance_variable_set("@#{key}", field)
        end
        File.write(path, report.to_yaml, mode: 'w', perm: 0o600)
        puts 'private native log must not be returned'
        exit(changed ? 2 : 0)
      RUBY
      File.write(File.join(dir, 'puppet'), fixture, mode: 'w', perm: 0o700)
      original = ENV.to_hash
      begin
        ENV['PATH'] = "#{dir}:#{ENV.fetch('PATH')}"
        ENV['PUPPET_AGENT_LOCK_FILE'] = File.join(dir, 'managed-agent.lock')
        result = described_class.run(expected, state_dir: dir, certname: 'fixture.nest', hostname: 'fixture', boot: -> { boot_id }, reader: ->(path) { File.read(path) })
        expect(result).to include('result' => 'pass', 'converged' => true, 'acceptance_recorded' => false)
        expect(result['main']['native_exit']).to eq(2)
        expect(result['repeat']['native_exit']).to eq(0)
        expect(result.to_s).not_to include('private native log')
        expect(Dir.children(dir).sort).to eq(['managed-agent.lock', 'puppet', 'systemctl'])
      ensure
        ENV.replace(original)
      end
    end
  end
end
