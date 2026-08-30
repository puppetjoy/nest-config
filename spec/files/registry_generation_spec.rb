require 'fileutils'
require 'open3'
require 'spec_helper'
require 'tmpdir'
require 'timeout'

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

      ['first', 'second'].each do |content|
        File.write(File.join(source, 'artifact'), content)
        _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
        expect(status).to be_success, stderr
      end

      stale = File.join(backup_root, 'generations', 'zz-stale-generation')
      FileUtils.mkdir_p(File.join(stale, 'data'))
      File.write(File.join(stale, '.complete'), "stale\n")
      File.write(File.join(stale, 'data', 'artifact'), 'stale')
      File.write(File.join(source, 'artifact'), 'third')
      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
      expect(status).to be_success, stderr

      generations = Dir.children(File.join(backup_root, 'generations')).sort
      expect(generations.length).to eq(2)
      expect(File.exist?(stale)).to be(false)
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

  it 'retires the legacy payload only after publishing the first generation' do
    Dir.mktmpdir('registry-legacy-migration') do |tmpdir|
      source = File.join(tmpdir, 'source')
      backup_root = File.join(tmpdir, 'backup')
      sync = File.join(tmpdir, 'sync')
      failed_sync = File.join(tmpdir, 'failed-sync')
      FileUtils.mkdir_p(source)
      FileUtils.mkdir_p(File.join(backup_root, 'docker'))
      File.write(File.join(backup_root, 'docker', 'legacy'), 'legacy')
      File.write(File.join(backup_root, '.legacy-object'), 'hidden')
      File.write(File.join(source, 'artifact'), 'first')
      write_sync(sync, 'cp -R "$1/." "$2"')
      write_sync(failed_sync, 'exit 42')

      _stdout, _stderr, status = Open3.capture3(backup_helper, backup_root, '--', failed_sync, source)
      expect(status.exitstatus).to eq(42)
      expect(File.read(File.join(backup_root, 'docker', 'legacy'))).to eq('legacy')
      expect(File.read(File.join(backup_root, '.legacy-object'))).to eq('hidden')

      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
      expect(status).to be_success, stderr
      first_generation = File.realpath(File.join(backup_root, 'current'))
      expect(File.read(File.join(first_generation, 'data', 'docker', 'legacy'))).to eq('legacy')
      expect(File.read(File.join(first_generation, 'data', '.legacy-object'))).to eq('hidden')
      expect(File.exist?(File.join(backup_root, 'docker'))).to be(false)
      expect(File.exist?(File.join(backup_root, '.legacy-object'))).to be(false)

      stale_retirement = File.join(backup_root, '.legacy-retired-interrupted')
      FileUtils.mkdir_p(stale_retirement)
      File.write(File.join(stale_retirement, 'retired-blocks'), 'safe to reap after publication')
      File.write(File.join(source, 'artifact'), 'second')
      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
      expect(status).to be_success, stderr
      expect(File.exist?(stale_retirement)).to be(false)
      expect(Dir.children(File.join(backup_root, 'generations')).length).to eq(2)
      expect(Dir.children(backup_root).sort).to eq(['.retired', '.staging', 'current', 'generations'])
      expect(File.read(File.join(File.realpath(File.join(backup_root, 'current')), 'data', 'artifact'))).to eq('second')
    end
  end

  it 'removes staging residue left by a hard-interrupted prior backup' do
    Dir.mktmpdir('registry-stale-staging') do |tmpdir|
      source = File.join(tmpdir, 'source')
      backup_root = File.join(tmpdir, 'backup')
      marker = File.join(tmpdir, 'sync-started')
      sync = File.join(tmpdir, 'sync')
      interrupted_sync = File.join(tmpdir, 'interrupted-sync')
      FileUtils.mkdir_p(source)
      File.write(File.join(source, 'artifact'), 'prior')
      write_sync(sync, 'cp -R "$1/." "$2"')
      write_sync(interrupted_sync, "touch #{marker}; sleep 30")

      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
      expect(status).to be_success, stderr
      published = File.readlink(File.join(backup_root, 'current'))
      File.write(File.join(source, 'artifact'), 'complete')

      pid = Process.spawn(backup_helper, backup_root, '--', interrupted_sync, source, pgroup: true)
      Timeout.timeout(5) { sleep 0.01 until File.exist?(marker) }
      Process.kill('KILL', -pid)
      _waited_pid, interrupted_status = Process.wait2(pid)
      expect(interrupted_status.termsig).to eq(Signal.list.fetch('KILL'))
      expect(Dir.children(File.join(backup_root, '.staging'))).not_to be_empty
      expect(File.readlink(File.join(backup_root, 'current'))).to eq(published)
      expect(File.read(File.join(File.realpath(File.join(backup_root, 'current')), 'data', 'artifact'))).to eq('prior')

      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
      expect(status).to be_success, stderr
      expect(Dir.children(File.join(backup_root, '.staging'))).to be_empty
      current = File.realpath(File.join(backup_root, 'current'))
      expect(File.read(File.join(current, 'data', 'artifact'))).to eq('complete')
    end
  end

  it 'finishes interrupted generation retirement before starting another sync' do
    Dir.mktmpdir('registry-stale-retirement') do |tmpdir|
      source = File.join(tmpdir, 'source')
      backup_root = File.join(tmpdir, 'backup')
      stale_retirement = File.join(backup_root, '.retired', 'interrupted')
      sync = File.join(tmpdir, 'sync')
      FileUtils.mkdir_p(source)
      FileUtils.mkdir_p(stale_retirement)
      File.write(File.join(source, 'artifact'), 'complete')
      File.write(File.join(stale_retirement, 'old-block'), 'safe to reap')
      write_sync(sync, "test ! -e #{stale_retirement}; cp -R \"$1/.\" \"$2\"")

      _stdout, stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync, source)
      expect(status).to be_success, stderr
      expect(Dir.children(File.join(backup_root, '.retired'))).to be_empty
      current = File.realpath(File.join(backup_root, 'current'))
      expect(File.read(File.join(current, 'data', 'artifact'))).to eq('complete')
    end
  end

  it 'refuses a completed generation entry that resolves outside the backup root' do
    Dir.mktmpdir('registry-generation-escape') do |tmpdir|
      backup_root = File.join(tmpdir, 'backup')
      generations = File.join(backup_root, 'generations')
      outside = File.join(tmpdir, 'outside')
      sync = File.join(tmpdir, 'sync')
      FileUtils.mkdir_p(File.join(outside, 'data'))
      FileUtils.mkdir_p(generations)
      File.write(File.join(outside, '.complete'), "outside\n")
      File.write(File.join(outside, 'data', 'artifact'), 'outside')
      File.symlink(outside, File.join(generations, 'escaped'))
      File.symlink('generations/escaped', File.join(backup_root, 'current'))
      write_sync(sync, 'exit 0')

      _stdout, _stderr, status = Open3.capture3(backup_helper, backup_root, '--', sync)
      expect(status).not_to be_success
      expect(File.read(File.join(outside, 'data', 'artifact'))).to eq('outside')
      expect(Dir.children(File.join(backup_root, '.staging'))).to be_empty
    end
  end

  it 'refuses restore from a nested generation path' do
    Dir.mktmpdir('registry-nested-generation') do |tmpdir|
      backup_root = File.join(tmpdir, 'backup')
      nested = File.join(backup_root, 'generations', 'outer', 'nested')
      destination = File.join(tmpdir, 'destination')
      sync = File.join(tmpdir, 'sync')
      FileUtils.mkdir_p(File.join(nested, 'data'))
      FileUtils.mkdir_p(destination)
      File.write(File.join(nested, '.complete'), "nested\n")
      File.write(File.join(nested, 'data', 'artifact'), 'must-not-restore')
      File.symlink('generations/outer/nested', File.join(backup_root, 'current'))
      write_sync(sync, 'cp -R "$1/." "$2"')

      _stdout, _stderr, status = Open3.capture3(restore_helper, backup_root, destination, '--', sync)
      expect(status).not_to be_success
      expect(Dir.children(destination)).to be_empty
    end
  end
end
