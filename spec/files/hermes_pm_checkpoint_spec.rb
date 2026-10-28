require 'open3'
require 'spec_helper'

RSpec.describe 'Hermes PM rolling source checkpoints' do
  let(:repo_root) { File.expand_path('../..', __dir__) }

  it 'executes local Git ancestry, rolling convergence and exact transaction regressions' do
    test_path = File.join(repo_root, 'spec/files/hermes_pm_checkpoint_test.py')
    stdout, stderr, status = Open3.capture3({ 'PYTHONDONTWRITEBYTECODE' => '1' }, 'python3', test_path)

    expect(status.success?).to be(true), "#{stdout}\n#{stderr}"
  end
end
