require 'open3'
require 'spec_helper'

RSpec.describe 'Secure browser generic safety boundaries' do
  let(:repo_root) { File.expand_path('../..', __dir__) }

  it 'executes generic tab identity, typing journal, editable control and link redaction regressions' do
    test_path = File.join(repo_root, 'spec/app/hermes/test_secure_browser_general_hardening.py')
    stdout, stderr, status = Open3.capture3({ 'PYTHONDONTWRITEBYTECODE' => '1' }, 'python3', test_path)

    expect(status.success?).to be(true), "#{stdout}\n#{stderr}"
  end
end
