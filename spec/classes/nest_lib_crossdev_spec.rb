require 'spec_helper'

# The generated overlay must not invalidate the complete frozen input inventory.
describe 'nest::lib::crossdev' do
  let(:pre_condition) { 'include nest' }

  on_supported_os.each do |os, os_facts|
    next unless os.match?(%r{^gentoo-})

    context "on #{os}" do
      let(:facts) { os_facts }

      it 'preserves the ordinary host repository location' do
        is_expected.to contain_nest__lib__repo('crossdev').with_location('/var/db/repos/crossdev')
      end

      ['stage0', 'stage1', 'stage2', 'stage3'].each do |stage|
        context "building #{stage}" do
          let(:facts) { os_facts.merge(build: stage) }

          it 'keeps generated overlay content outside the pinned repositories' do
            is_expected.to contain_nest__lib__repo('crossdev').with_location('/var/lib/portage/crossdev')
            is_expected.to contain_file('/etc/portage/repos.conf/crossdev.conf').with_content(%r{location = /var/lib/portage/crossdev\n})
            is_expected.not_to contain_file('/var/db/repos/crossdev')
            is_expected.to contain_file('/var/lib/portage/crossdev/metadata/layout.conf')
            is_expected.to contain_file('/var/lib/portage/crossdev/profiles/repo_name')
          end
        end
      end
    end
  end
end
