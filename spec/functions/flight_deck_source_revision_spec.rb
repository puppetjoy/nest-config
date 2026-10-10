require 'spec_helper'
require 'yaml'
require 'tmpdir'
require 'fileutils'
require 'open3'

describe 'nest::kubernetes::flight_deck_source_revision' do
  let(:revision) { 'a' * 40 }

  before(:each) do
    allow(YAML).to receive(:safe_load_file).and_call_original
    allow(YAML).to receive(:safe_load_file).with(%r{/data/kubernetes/service/flight-deck-dev\.yaml\z}).and_return('flight_deck_source_revision' => revision)
  end

  it { is_expected.to run.with_params('flight-deck-dev', revision).and_return(true) }
  it { is_expected.to run.with_params('flight-deck-dev', '').and_return(true) }
  it { is_expected.to run.with_params('flight-deck', '').and_return(true) }
  it { is_expected.to run.with_params('flight-deck-dev', 'b' * 40).and_raise_error(%r{must match source-managed}) }
  it { is_expected.to run.with_params('flight-deck-dev', 'main').and_raise_error(ArgumentError) }
  it { is_expected.to run.with_params('flight-deck-dev', 'a' * 39).and_raise_error(ArgumentError) }
  it { is_expected.to run.with_params('flight-deck-dev', 'A' * 40).and_raise_error(ArgumentError) }
  it { is_expected.to run.with_params('../flight-deck', '').and_raise_error(ArgumentError) }

  context 'with invalid desired data' do
    let(:revision) { 'main' }

    it { is_expected.to run.with_params('flight-deck-dev', '').and_raise_error(%r{full lowercase 40-hex SHA}) }
  end
  # The source fetch is an integration boundary: exercise the actual init script.
  context 'Flight Deck source checkout' do
    let(:root) { File.expand_path('../..', __dir__) }
    let(:data) { YAML.safe_load_file(File.join(root, 'data/kubernetes/app/flight-deck.yaml'), aliases: true) }
    let(:deployment) { data.fetch('resources').fetch('deployment') }
    let(:fetch) { deployment.fetch('spec').fetch('template').fetch('spec').fetch('initContainers').first }
    let(:scratch) do
      build = File.join(root, 'build')
      FileUtils.mkdir_p(build)
      Dir.mktmpdir('flight-deck-spec-', build)
    end
    let(:repo) { File.join(scratch, 'repo') }
    let(:accepted) { command('git', '-C', repo, 'rev-parse', 'HEAD~1') }
    let(:latest) { command('git', '-C', repo, 'rev-parse', 'HEAD') }

    def command(*args)
      output, status = Open3.capture2e(*args)
      raise output unless status.success?

      output.strip
    end

    def checkout(revision)
      script = fetch.fetch('command').last.gsub('/work/', "#{scratch}/work/")
      Open3.capture2e({ 'FLIGHT_DECK_REPO' => repo, 'FLIGHT_DECK_REF_NAME' => 'main', 'FLIGHT_DECK_SOURCE_REVISION' => revision }, 'sh', '-ceu', script)
    end

    before(:each) do
      command('git', 'init', '--initial-branch=main', repo)
      File.write(File.join(repo, 'engineering.py'), 'accepted source')
      command('git', '-C', repo, 'add', '.')
      command('git', '-C', repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-m', 'accepted')
      File.write(File.join(repo, 'engineering.py'), 'newer source')
      command('git', '-C', repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-am', 'newer')
    end

    after(:each) do
      FileUtils.remove_entry(scratch)
    end

    it 'rolls the pod template when the source-managed revision changes' do
      expect(deployment.fetch('spec').fetch('template').fetch('metadata').fetch('annotations').fetch('joyfullee.me/source-revision')).to eq("%{lookup('flight_deck_source_revision')}")
      expect(fetch.fetch('env')).to include('name' => 'FLIGHT_DECK_SOURCE_REVISION', 'value' => "%{lookup('flight_deck_source_revision')}")
    end

    it 'checks out and records the exact accepted source even when main has advanced' do
      output, status = checkout(accepted)
      expect(status.success?).to be(true), output
      expect(File.read(File.join(scratch, 'work/flight-deck/engineering.py'))).to eq('accepted source')
      expect(File.read(File.join(scratch, 'work/flight-deck/.flight-deck-source-revision')).strip).to eq(accepted)
      expect(command('git', '-C', File.join(scratch, 'work/flight-deck'), 'rev-parse', 'HEAD')).to eq(accepted)
    end

    it 'retains repo/ref behavior when the revision is unset' do
      output, status = checkout('')
      expect(status.success?).to be(true), output
      expect(File.read(File.join(scratch, 'work/flight-deck/.flight-deck-source-revision')).strip).to eq(latest)
    end

    it 'rejects malformed revision data before fetching source' do
      output, status = checkout('main')
      expect(status.success?).to be(false)
      expect(output).to include('full lowercase 40-hex SHA')
    end

    it 'fails closed when an exact revision cannot be fetched' do
      _output, status = checkout('0' * 40)
      expect(status.success?).to be(false)
      expect(File).not_to exist(File.join(scratch, 'work/flight-deck/.flight-deck-source-revision'))
    end
  end
end
