# frozen_string_literal: true

require 'yaml'

# Deployment parameters assert committed desired state; they never override it.
Puppet::Functions.create_function(:'nest::kubernetes::flight_deck_source_revision') do
  dispatch :validate do
    param "Enum['flight-deck-dev', 'flight-deck']", :service
    param "Variant[Pattern[/\\A[0-9a-f]{40}\\z/], Enum['']]", :source_revision
    return_type 'Boolean'
  end

  def validate(service, source_revision)
    mod = closure_scope.environment.module('nest')
    data = YAML.safe_load_file(File.join(mod.path, 'data', 'kubernetes', 'service', "#{service}.yaml"))
    desired = data.fetch('flight_deck_source_revision', '')
    unless desired.is_a?(String) && (desired.empty? || desired.match?(%r{\A[0-9a-f]{40}\z}))
      raise Puppet::Error, 'flight_deck_source_revision must be empty or a full lowercase 40-hex SHA'
    end
    unless source_revision.empty? || source_revision == desired
      raise Puppet::Error, "Flight Deck #{service} source_revision must match source-managed flight_deck_source_revision"
    end

    true
  end
end
