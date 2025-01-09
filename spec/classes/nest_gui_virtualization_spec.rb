require 'spec_helper'

describe 'nest::gui::virtualization' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^gentoo-}
      context 'on Gentoo' do
        let(:facts) do
          facts.merge({ profile: { variant: 'workstation' } })
        end

        it { is_expected.to contain_package('app-emulation/virt-viewer').that_requires('Class[nest::base::zfs]') }
      end
    end
  end
end
