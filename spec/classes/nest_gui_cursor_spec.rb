require 'spec_helper'

describe 'nest::gui::cursor' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^gentoo-}
      context 'on Gentoo' do
        let(:facts) do
          facts.merge({ profile: { variant: 'workstation' } })
        end

        it { is_expected.to contain_file('/usr/share/icons/breeze_cursors').that_requires('Class[nest::gui::plasma]') }
        it { is_expected.to contain_file('/usr/share/icons/Breeze_Snow').that_requires('Class[nest::gui::plasma]') }
      end
    end
  end
end
