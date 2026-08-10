require 'spec_helper'

RSpec.describe 'registry backup and restore serialization' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:backup_plan) { File.read(File.join(repo_root, 'plans/eyrie/registry/backup.pp')) }
  let(:restore_plan) { File.read(File.join(repo_root, 'plans/eyrie/registry/restore.pp')) }

  it 'waits for the shared lock instead of dropping colliding generations' do
    [backup_plan, restore_plan].each do |plan|
      expect(plan).to match(%r{'flock',\n\s+'--exclusive',\n\s+\$lock_file,})
      expect(plan).not_to include("'--nonblock'")
    end
  end
end
