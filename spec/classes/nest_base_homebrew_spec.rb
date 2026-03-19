require 'spec_helper'

describe 'nest::base::homebrew' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^darwin-}
      context 'on macOS' do
        let(:facts) do
          os_facts = facts[:os] || facts['os']
          release_facts = os_facts[:release] || os_facts['release']

          facts.merge(
            homebrew_clt_installed: true,
            homebrew_owner: 'joy',
            identity: { 'user' => 'root' },
            os: os_facts.merge(
              architecture: 'arm64',
              release: release_facts.merge(major: '25'),
            ),
          )
        end

        let(:post_condition) do
          <<~PP
          package { 'foo':
            ensure   => installed,
            provider => homebrew,
          }
          PP
        end

        it { is_expected.to contain_class('homebrew').with_install_user('joy') }
        it { is_expected.to contain_class('homebrew').that_comes_before('Package[foo]') }
      end
    end
  end
end
