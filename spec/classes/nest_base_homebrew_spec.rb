require 'spec_helper'

describe 'nest::base::homebrew' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^darwin-}
      context 'on macOS' do
        let(:facts) do
          facts
        end

        let(:post_condition) do
          <<~PP
          package { 'foo':
            ensure   => installed,
            provider => homebrew,
          }
          PP
        end

        it { is_expected.to contain_class('homebrew').that_requires('Class[nest::base::sudo]') }
        it { is_expected.to contain_class('homebrew').that_comes_before('Package[foo]') }
      end
    end
  end
end
