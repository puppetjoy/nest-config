require 'spec_helper'

describe 'nest::lib::package_use' do
  let(:pre_condition) { 'include nest' }

  let(:title) { 'foo/bar' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^gentoo-}
      context 'on Gentoo' do
        let(:facts) do
          facts
        end

        let(:post_condition) do
          <<~PP
          package { 'foo/bar':
            ensure => installed,
          }
          PP
        end

        it { is_expected.to contain_exec('emerge-newuse-foo/bar').that_subscribes_to('Package_use[foo/bar]') }
        it { is_expected.to contain_package('foo/bar').that_subscribes_to('Exec[emerge-newuse-foo/bar]') }
      end
    end
  end
end
