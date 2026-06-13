require 'spec_helper'

describe 'nest::usbnet_stable_mac' do
  it 'derives the device address from machine-id bytes with a local unicast prefix' do
    is_expected.to run.with_params('00112233445566778899aabbccddeeff', 'dev').and_return('02:00:11:22:33:44')
  end

  it 'derives a distinct host address from the same seed' do
    is_expected.to run.with_params('00112233445566778899aabbccddeeff', 'host').and_return('06:00:11:22:33:44')
  end

  it 'ignores non-hex separators in the machine-id value' do
    is_expected.to run.with_params('00-11-22-33-44-55-66-77', 'dev').and_return('02:00:11:22:33:44')
  end
end
