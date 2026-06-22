require 'spec_helper'

describe 'nest::service::gitlab' do
  on_supported_os.each do |os, facts|
    next unless os.match?(%r{^gentoo-})

    context 'on Gentoo without nest::kubernetes in scope' do
      let(:facts) do
        facts
      end

      let(:params) do
        {
          external_name: 'gitlab.localhost',
        }
      end

      it { is_expected.to compile }
    end
  end
end
