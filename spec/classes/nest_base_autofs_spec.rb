require 'spec_helper'

describe 'nest::base::autofs' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, facts|
    case os
    when %r{^darwin-}
      context 'on macOS' do
        let(:facts) do
          facts
        end

        it do
          is_expected.to contain_file('/Volumes/nest').with(
            ensure: 'directory',
            mode: '0755',
            owner: 'root',
            group: 'wheel'
          )
        end

        it do
          is_expected.to contain_file_line('auto_master-/Volumes/nest').with(
            path: '/etc/auto_master',
            line: '/Volumes/nest auto_nest',
            match: '^/Volumes/nest\s+'
          )
        end

        it do
          is_expected.to contain_file('/etc/auto_nest').with(
            mode: '0644',
            owner: 'root',
            group: 'wheel',
            content: "home -fstype=nfs,noowners,vers=4 falcon.nest:/nest/home\n"
          )
        end

        it do
          is_expected.to contain_exec('automount-reload').with(
            command: '/usr/sbin/automount -vc',
            refreshonly: true
          )
        end

        it { is_expected.to contain_file('/Volumes/nest').that_notifies('Exec[automount-reload]') }
        it { is_expected.to contain_file_line('auto_master-/Volumes/nest').that_notifies('Exec[automount-reload]') }
        it { is_expected.to contain_file('/etc/auto_nest').that_notifies('Exec[automount-reload]') }

        it do
          is_expected.to contain_file('/etc/synthetic.d').with(
            ensure: 'directory',
            mode: '0755',
            owner: 'root',
            group: 'wheel'
          )
        end

        it do
          is_expected.to contain_file('/etc/synthetic.d/nest.conf').with(
            mode: '0644',
            owner: 'root',
            group: 'wheel',
            content: "nest\tVolumes/nest\n"
          )
        end

        it { is_expected.to contain_file('/etc/synthetic.d/nest.conf').that_requires('File[/etc/synthetic.d]') }
      end
    end
  end
end
