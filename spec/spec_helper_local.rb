# frozen_string_literal: true

RSpec.configure do |config|
  config.after :each do
    # RunMode caches by mode name, not platform. A Windows catalog example
    # can otherwise leave Windows paths cached for a later native Bolt PAL.
    Puppet::Util::RunMode.instance_variable_set(:@run_modes, {})
  end
end

def it_should_and_should_not_contain_classes(should, should_not = [])
  it 'checks class inclusion and exclusion for the platform matrix', :aggregate_failures do
    should.each { |c| is_expected.to contain_class(c) }
    (should_not - should).each { |c| is_expected.not_to contain_class(c) }
  end
end
