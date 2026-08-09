require 'fileutils'
require 'open3'
require 'spec_helper'
require 'tmpdir'

RSpec.describe 'registry backup generations' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:backup_helper) { File.join(repo_root, 'files/registry-backup-generation') }
  let(:restore_helper) { File.join(repo_root, 'files/registry-restore-generation') }

  def write_sync(path, body)
    File.write(path, "#!/bin/sh\nset -eu\n#{body}\n")
    FileUtils.chmod(0o700, path)
  end

  it 'keeps the prior completed generation current when a later backup is interrupted' do
    Dir.mktmpdir('registry-generations') do |tmpdir|
      source = File.join(tmpdir, 'source')
      backup_root = File.join(tmpdir, 'backup')
      restored = File.join(tmpdir, 'restored')
      successful_sync = File.join(tmpdir, 'successful-sync')
      interrupted_sync = File.join(tmpdir, 'interrupted-sync')
      FileUtils.mkdir_p(source)
      File.write(File.join(source, 'artifact'), 'complete-generation')
      write_sync(successful_sync, 'cp -R "$1/." "$2"')
      write_sync(interrupted_sync, 'cp "$1/artifact" "$2/partial"; exit 42')

      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', successful_sync, source)
      expect(status).to be_success, stderr
      published = File.readlink(File.join(backup_root, 'current'))

      File.write(File.join(source, 'artifact'), 'interrupted-generation')
      _stdout, _stderr, status = Open3.capture3(backup_helper, backup_root, '--', interrupted_sync, source)
      expect(status.exitstatus).to eq(42)
      expect(File.readlink(File.join(backup_root, 'current'))).to eq(published)
      expect(Dir.children(File.join(backup_root, '.staging'))).to be_empty

      FileUtils.mkdir_p(restored)
      _stdout, stderr, status = Open3.capture3(restore_helper, backup_root, restored, '--', successful_sync)
      expect(status).to be_success, stderr
      expect(File.read(File.join(restored, 'artifact'))).to eq('complete-generation')
      expect(File.exist?(File.join(restored, '.complete'))).to be(false)
    end
  end

  it 'block-clones the prior payload and retains only two completed generations' do
    Dir.mktmpdir('registry-generation-retention') do |tmpdir|
      source = File.join(tmpdir, 'source')
      backup_root = File.join(tmpdir, 'backup')
      sync = File.join(tmpdir, 'sync')
      FileUtils.mkdir_p(source)
      write_sync(sync, 'cp -R "$1/." "$2"')

      ['first', 'second', 'third'].each do |content|
        File.write(File.join(source, 'artifact'), content)
        _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
        expect(status).to be_success, stderr
      end

      generations = Dir.children(File.join(backup_root, 'generations')).sort
      expect(generations.length).to eq(2)
      current = File.realpath(File.join(backup_root, 'current'))
      expect(File.read(File.join(current, 'data', 'artifact'))).to eq('third')
      prior = (generations.map { |name| File.join(backup_root, 'generations', name) } - [current]).fetch(0)
      expect(File.read(File.join(prior, 'data', 'artifact'))).to eq('second')
    end
  end

  it 'refuses a current pointer without a completed-generation marker' do
    Dir.mktmpdir('registry-incomplete') do |tmpdir|
      backup_root = File.join(tmpdir, 'backup')
      incomplete = File.join(backup_root, 'generations', 'incomplete')
      destination = File.join(tmpdir, 'destination')
      sync = File.join(tmpdir, 'sync')
      FileUtils.mkdir_p(incomplete)
      FileUtils.mkdir_p(destination)
      File.symlink('generations/incomplete', File.join(backup_root, 'current'))
      write_sync(sync, 'cp -R "$1/." "$2"')

      _stdout, _stderr, status = Open3.capture3(restore_helper, backup_root, destination, '--', sync)
      expect(status).not_to be_success
      expect(Dir.children(destination)).to be_empty
    end
  end
end
