# frozen_string_literal: true

require 'open3'
require 'tmpdir'

RSpec.describe 'manage-hermes-env' do
  let(:helper) { File.expand_path('../../files/app/hermes/manage-hermes-env.py', __dir__) }

  it 'preserves only named runtime credentials while converging managed content' do
    Dir.mktmpdir('hermes-env') do |tmpdir|
      base = File.join(tmpdir, 'managed.env')
      target = File.join(tmpdir, '.env')
      File.write(base, "TELEGRAM_BOT_TOKEN=managed\n")
      File.write(target, "TELEGRAM_BOT_TOKEN=stale\nCOPILOT_GITHUB_TOKEN='runtime'\nUNMANAGED=drop\n")
      File.chmod(0o644, target)

      _stdout, stderr, status = Open3.capture3(
        'python3',
        helper,
        'sync',
        '--base', base,
        '--target', target,
        '--preserve', 'COPILOT_GITHUB_TOKEN'
      )

      expect(status).to be_success, stderr
      expect(File.read(target)).to eq("TELEGRAM_BOT_TOKEN=managed\nCOPILOT_GITHUB_TOKEN='runtime'\n")
      expect(File.stat(target).mode & 0o777).to eq(0o600)

      _stdout, stderr, status = Open3.capture3(
        'python3',
        helper,
        'check',
        '--base', base,
        '--target', target,
        '--preserve', 'COPILOT_GITHUB_TOKEN'
      )
      expect(status).to be_success, stderr
    end
  end

  it 'refuses keys claimed by both Puppet and the runtime' do
    Dir.mktmpdir('hermes-env-overlap') do |tmpdir|
      base = File.join(tmpdir, 'managed.env')
      target = File.join(tmpdir, '.env')
      File.write(base, "COPILOT_GITHUB_TOKEN=managed\n")
      File.write(target, "COPILOT_GITHUB_TOKEN=runtime\n")

      _stdout, stderr, status = Open3.capture3(
        'python3',
        helper,
        'sync',
        '--base', base,
        '--target', target,
        '--preserve', 'COPILOT_GITHUB_TOKEN'
      )

      expect(status).not_to be_success
      expect(stderr).to include('runtime-owned key is also administrator-managed')
      expect(File.read(target)).to eq("COPILOT_GITHUB_TOKEN=runtime\n")
    end
  end
end
