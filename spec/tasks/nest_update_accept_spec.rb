require 'spec_helper'
require 'tmpdir'
require_relative '../../tasks/update_accept'

RSpec.describe NestUpdateAccept do
  let(:directory) { Dir.mktmpdir('nest-accept-spec-') }
  let(:evidence) { { 'kind' => 'reset_acceptance_evidence' } }
  let(:params) { { 'transaction' => 'fixture', 'evidence' => evidence } }

  after :each do
    FileUtils.remove_entry(directory)
  end

  it 'passes private exact evidence to the native CLI and removes the temporary copy' do
    runner = ->(*args) do
      expect(args.take(4)).to eq(['nest', 'reset', 'accept', 'fixture'])
      expect(args.last).to eq('--format=json')
      path = args[5]
      expect(JSON.parse(File.read(path))).to eq(evidence)
      expect(File.stat(path).mode & 0o777).to eq(0o600)
      report = { 'kind' => 'reset_transaction_report', 'id' => 'fixture', 'accepted' => true, 'acceptance' => { 'evidence' => evidence } }
      [report.to_json, '', instance_double(Process::Status, success?: true)]
    end

    expect(described_class.run(params, directory: directory, runner: runner)).to eq('accepted' => true)
    expect(Dir.children(directory)).to be_empty
  end

  it 'does not turn failed native acceptance or mismatched evidence into success' do
    runner = ->(*_args) { ['{}', '', instance_double(Process::Status, success?: false)] }

    expect { described_class.run(params, directory: directory, runner: runner) }.to raise_error(RuntimeError)
    expect(Dir.children(directory)).to be_empty
  end

  it 'refuses malformed transaction IDs before invoking native code' do
    runner = ->(*_args) { raise 'must not invoke' }

    expect { described_class.run(params.merge('transaction' => '../bad'), directory: directory, runner: runner) }.to raise_error(RuntimeError, 'Invalid acceptance parameters')
  end
end
