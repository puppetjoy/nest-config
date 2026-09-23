require 'open3'
require 'spec_helper'

RSpec.describe 'Hermes full-home backup generations' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:backup_plan) { File.read(File.join(repo_root, 'plans/app/hermes/backup.pp')) }
  let(:restore_plan) { File.read(File.join(repo_root, 'plans/app/hermes/restore.pp')) }
  let(:dashboard_data) { File.read(File.join(repo_root, 'data/kubernetes/app/hermes-dashboard.yaml')) }

  it 'passes no profile label to the native full backup or import commands' do
    expect(backup_plan).not_to match(%r{hermes.*--profile.*backup --output})
    expect(restore_plan).not_to match(%r{hermes.*--profile.*import})
    expect(dashboard_data).not_to match(%r{"(?:profile|service_name)=})
  end

  it 'hands the private uploaded helper to the unprivileged backup account' do
    expect(backup_plan).to include('chown ${user.shellquote}:${user.shellquote} ${helper.shellquote}')
    expect(backup_plan).to include('chmod 0700 ${helper.shellquote}')
    expect(backup_plan).to include('runuser -u ${user.shellquote} -- ${helper_args.shellquote}')
  end

  it 'stops every required profile service around a shared-root restore' do
    expect(restore_plan).to include("['talon', 'star', 'beryl', 'quill']")
    expect(restore_plan).to include('for restore_profile in ${profile_args}')
    expect(restore_plan).to include('/opt/hermes-agent/venv/bin/hermes import')
  end

  it 'creates, verifies, restores, retains, and migrates generations safely' do
    test_path = File.join(repo_root, 'spec/files/hermes_backup_generation_test.py')
    _stdout, stderr, status = Open3.capture3('python3', test_path)

    expect(status).to be_success, stderr
  end
end
