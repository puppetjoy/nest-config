require 'spec_helper'

describe 'nest::gui::input' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^gentoo-}
      context 'on Gentoo' do
        let(:facts) do
          facts.merge({ profile: { variant: 'workstation' } })
        end

        it { is_expected.to contain_file('/etc/libinput').that_requires('Class[nest::gui::xorg]') }
      end
    end
  end
end
