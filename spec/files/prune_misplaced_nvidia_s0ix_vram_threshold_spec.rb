# frozen_string_literal: true

require 'spec_helper'
require 'open3'
require 'tmpdir'

RSpec.describe 'prune-misplaced-nvidia-s0ix-vram-threshold' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:script) { File.join(repo_root, 'files/host/osprey/prune-misplaced-nvidia-s0ix-vram-threshold.rb') }
  let(:valid_block) do
    <<~'CONF'
      options nvidia \
        NVreg_PreserveVideoMemoryAllocations=1 \
        NVreg_S0ixPowerManagementVideoMemoryThreshold=10000 \
        NVreg_TemporaryFilePath=/var/tmp
      remove nvidia /sbin/modprobe -r --ignore-remove nvidia
    CONF
  end

  def run_script(*arguments)
    Open3.capture3(RbConfig.ruby, script, *arguments)
  end

  it 'removes an identical threshold line outside the NVIDIA options block' do
    Dir.mktmpdir do |directory|
      config = File.join(directory, 'nvidia.conf')
      threshold_line = valid_block.lines.find { |line| line.include?('NVreg_S0ixPowerManagementVideoMemoryThreshold=') }
      malformed_config = valid_block.lines.reject { |line| line == threshold_line }.join + threshold_line
      File.write(config, malformed_config)

      _stdout, stderr, check_status = run_script('--check', config)
      expect(check_status).to be_success, stderr

      _stdout, stderr, repair_status = run_script(config)
      expect(repair_status).to be_success, stderr
      expect(File.read(config)).not_to include('NVreg_S0ixPowerManagementVideoMemoryThreshold=')
    end
  end

  it 'leaves a correctly placed threshold line unchanged' do
    Dir.mktmpdir do |directory|
      config = File.join(directory, 'nvidia.conf')
      File.write(config, valid_block)

      _stdout, _stderr, check_status = run_script('--check', config)
      expect(check_status).not_to be_success
      expect(File.read(config)).to eq(valid_block)
    end
  end
end
