# frozen_string_literal: true

require 'puppet-lint'
require_relative '../../lib/puppet-lint/plugins/check_parameter_list_alignment'

RSpec.describe 'parameter_list_alignment puppet-lint check' do
  def problems_for(code)
    PuppetLint::Data.path = 'plans/restore.pp'
    PuppetLint::Data.manifest_lines = code.split("\n", -1)

    PuppetLint::CheckParameterListAlignment.new.run
  end

  it 'rejects a default whose equals sign is not aligned because the parameter name is not padded' do
    problems = problems_for(<<~'PUPPET')
      plan nest::eyrie::gitlab::restore (
        TargetSpec       $targets      = 'eyrie-workstations',
        String           $namespace    = 'test',
        String           $service      = 'gitlab',
        Optional[String] $service_name = undef, # unused
        String           $home_page_url= "https://${service}-${namespace}.eyrie/explore",
        Boolean          $restore      = false,
      ) {
      }
    PUPPET

    expect(problems).to include(
      hash_including(
        check: :parameter_list_alignment,
        kind: :warning,
        line: 6,
        message: 'parameter default equals sign should be padded after the parameter name',
      ),
    )
  end

  it 'accepts the same parameter list when the parameter name column is padded before each equals sign' do
    problems = problems_for(<<~'PUPPET')
      plan nest::eyrie::gitlab::restore (
        TargetSpec       $targets       = 'eyrie-workstations',
        String           $namespace     = 'test',
        String           $service       = 'gitlab',
        Optional[String] $service_name  = undef, # unused
        String           $home_page_url = "https://${service}-${namespace}.eyrie/explore",
        Boolean          $restore       = false,
      ) {
      }
    PUPPET

    expect(problems).to be_empty
  end
end
