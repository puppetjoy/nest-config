require 'spec_helper'

describe 'nest' do
  stage0 = [
    'nest::base::distcc',
    'nest::base::locale',
    'nest::base::portage',
  ]

  stage1 = [
    'nest::base::bird',
    'nest::base::branding',
    'nest::base::certs',
    'nest::base::cli',
    'nest::base::containers',
    'nest::base::distcc',
    'nest::base::distccd',
    'nest::base::eyaml',
    'nest::base::fail2ban',
    'nest::base::firewall',
    'nest::base::fs',
    'nest::base::gentoo',
    'nest::base::git',
    'nest::base::hosts',
    'nest::base::locale',
    'nest::base::mta',
    'nest::base::network',
    'nest::base::openvpn',
    'nest::base::packages',
    'nest::base::portage',
    'nest::base::puppet',
    'nest::base::qemu',
    'nest::base::ruby',
    'nest::base::scripts',
    'nest::base::ssh',
    'nest::base::sudo',
    'nest::base::syslog',
    'nest::base::systemd',
    'nest::base::timesyncd',
    'nest::base::users',
    'nest::base::vmware',
    'nest::base::wifi',
    'nest::base::zfs',
  ]

  stage2 = [
    'nest::base::console',
    'nest::base::dracut',
    'nest::base::firmware',
    'nest::base::fstab',
    'nest::base::kernel',
    'nest::base::plymouth',
  ]

  stage3 = [
    'nest::base::bootloader',
    'nest::base::kexec',
  ]

  windows = [
    'nest::base::certs',
    'nest::base::chocolatey',
    'nest::base::cygwin',
    'nest::base::eyaml',
    'nest::base::firewall',
    'nest::base::git',
    'nest::base::openvpn',
    'nest::base::packages',
    'nest::base::puppet',
    'nest::base::qemu',
    'nest::base::ssh',
    'nest::base::syslog',
    'nest::base::users',
    'nest::base::vmware',
    'nest::gui::chrome',
    'nest::gui::firefox',
    'nest::gui::fonts',
    'nest::gui::terminals',
    'nest::gui::xorg',
  ]

  workstation = [
    'nest::gui::bitwarden',
    'nest::gui::chrome',
    'nest::gui::cups',
    'nest::gui::cursor',
    'nest::gui::dunst',
    'nest::gui::firefox',
    'nest::gui::fonts',
    'nest::gui::greetd',
    'nest::gui::input',
    'nest::gui::media',
    'nest::gui::packages',
    'nest::gui::pipewire',
    'nest::gui::plasma',
    'nest::gui::policykit',
    'nest::gui::sway',
    'nest::gui::terminals',
    'nest::gui::virtualization',
    'nest::gui::xmonad',
    'nest::gui::xorg',
    'nest::gui::zoom',
    'nest::service::bluetooth',
    'nest::tool::bolt',
    'nest::tool::pdk',
    'nest::tool::qemu',
  ]

  on_supported_os.each do |os, facts|
    case os
    when %r{^gentoo-}
      context 'on Gentoo' do
        let(:facts) do
          facts
        end

        it_should_and_should_not_contain_classes(stage1 + stage2 + stage3, windows + workstation)

        context 'and variant => workstation' do # rubocop:disable RSpec/EmptyExampleGroup
          let(:facts) do
            facts.merge({ profile: { variant: 'workstation' } })
          end

          it_should_and_should_not_contain_classes(workstation)
        end

        context 'building stage0' do # rubocop:disable RSpec/EmptyExampleGroup
          let(:facts) do
            facts.merge({ build: 'stage0' })
          end

          it_should_and_should_not_contain_classes(stage0, stage1 + stage2 + stage3 + windows + workstation - stage0)
        end

        context 'building stage1' do
          let(:facts) do
            facts.merge({ build: 'stage1' })
          end

          it_should_and_should_not_contain_classes(stage1, stage2 + stage3 + windows + workstation)

          context 'and variant => workstation' do # rubocop:disable RSpec/EmptyExampleGroup
            let(:facts) do
              facts.merge({ build: 'stage1', profile: { variant: 'workstation' } })
            end

            it_should_and_should_not_contain_classes(workstation)
          end
        end

        context 'building stage2' do
          let(:facts) do
            facts.merge({ build: 'stage2' })
          end

          it_should_and_should_not_contain_classes(stage1 + stage2, stage3 + windows + workstation)

          context 'and variant => workstation' do # rubocop:disable RSpec/EmptyExampleGroup
            let(:facts) do
              facts.merge({ build: 'stage2', profile: { variant: 'workstation' } })
            end

            it_should_and_should_not_contain_classes(workstation)
          end
        end

        shared_examples 'stage3' do
          it_should_and_should_not_contain_classes(stage1 + stage2 + stage3, windows + workstation)
        end

        context 'building stage3' do
          let(:facts) do
            facts.merge({ build: 'stage3' })
          end

          it_behaves_like 'stage3'

          context 'and variant => workstation' do # rubocop:disable RSpec/EmptyExampleGroup
            let(:facts) do
              facts.merge({ build: 'stage3', profile: { variant: 'workstation' } })
            end

            it_should_and_should_not_contain_classes(workstation)
          end
        end

        context 'building kernel' do
          let(:facts) do
            facts.merge({ build: 'kernel' })
          end

          it_behaves_like 'stage3'
        end

        context 'building bolt' do # rubocop:disable RSpec/EmptyExampleGroup
          let(:facts) do
            facts.merge({ build: 'bolt' })
          end

          it_should_and_should_not_contain_classes(stage1 + ['nest::tool::bolt'], stage2 + stage3 + windows + workstation)
        end

        context 'building chromium' do # rubocop:disable RSpec/EmptyExampleGroup
          let(:facts) do
            facts.merge({ build: 'chromium', profile: { variant: 'workstation' } })
          end

          it_should_and_should_not_contain_classes(stage1 + workstation, stage2 + stage3 + windows)
        end

        context 'building pdk' do # rubocop:disable RSpec/EmptyExampleGroup
          let(:facts) do
            facts.merge({ build: 'pdk' })
          end

          it_should_and_should_not_contain_classes(stage1 + ['nest::tool::pdk'], stage2 + stage3 + windows + workstation)
        end

        context 'building r10k' do # rubocop:disable RSpec/EmptyExampleGroup
          let(:facts) do
            facts.merge({ build: 'r10k' })
          end

          it_should_and_should_not_contain_classes(stage1 + ['nest::tool::r10k'], stage2 + stage3 + windows + workstation)
        end
      end

    when %r{^windows-}
      context 'on Windows' do # rubocop:disable RSpec/EmptyExampleGroup
        let(:facts) do
          facts
        end

        it_should_and_should_not_contain_classes(windows, stage1 + stage2 + stage3 + workstation)
      end
    end
  end
end
