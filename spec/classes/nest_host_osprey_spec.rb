require 'spec_helper'

describe 'nest::host::osprey' do
  let(:pre_condition) do
    <<~PUPPET
      class nest::base::dracut {}
      include nest::base::dracut
    PUPPET
  end

  it do
    is_expected.to contain_file('/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold').with(
      mode: '0755',
      source: 'puppet:///modules/nest/host/osprey/prune-misplaced-nvidia-s0ix-vram-threshold.rb',
    )

    is_expected.to contain_exec('prune-misplaced-nvidia-s0ix-vram-threshold').with(
      command: '/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold /etc/modprobe.d/nvidia.conf',
      onlyif: '/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold --check /etc/modprobe.d/nvidia.conf',
      require: [
        'File[/usr/local/libexec/nest-prune-misplaced-nvidia-s0ix-vram-threshold]',
        'File_line[nvidia.conf-enable-s0ix-power-management]',
      ],
    ).that_notifies('Class[nest::base::dracut]')

    is_expected.to contain_file_line('nvidia.conf-s0ix-vram-threshold').with(
      path: '/etc/modprobe.d/nvidia.conf',
      line: '  NVreg_S0ixPowerManagementVideoMemoryThreshold=10000 \\',
      match: '^\\s*NVreg_S0ixPowerManagementVideoMemoryThreshold=',
      after: '^\\s*NVreg_PreserveVideoMemoryAllocations=1 \\$',
      require: 'Exec[prune-misplaced-nvidia-s0ix-vram-threshold]',
    ).that_notifies('Class[nest::base::dracut]')
  end
end
