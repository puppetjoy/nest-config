require 'spec_helper'

describe 'nest::base::wsl' do # rubocop:disable RSpec/EmptyExampleGroup
  on_supported_os.each do |os, facts|
    case os
    when %r{^windows-}
      context 'on Windows' do
        let(:facts) do
          facts
        end

        context 'when wsl fact reports ready' do
          let(:facts) do
            facts.merge(
              'wsl' => {
                'features_enabled' => true,
                'reboot_pending'   => false,
                'ready'            => true,
              },
            )
          end

          it { is_expected.to contain_exec('nest-wsl-import-distribution-initial') }
          it { is_expected.not_to contain_notify('nest-wsl-reboot-required') }
        end

        context 'when wsl fact reports reboot pending' do
          let(:facts) do
            facts.merge(
              'wsl' => {
                'features_enabled' => true,
                'reboot_pending'   => true,
                'ready'            => false,
              },
            )
          end

          it { is_expected.not_to contain_exec('nest-wsl-import-distribution-initial') }
          it { is_expected.to contain_notify('nest-wsl-reboot-required') }
        end
      end
    end
  end
end
