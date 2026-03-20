# frozen_string_literal: true

RSpec.configure do |c|
  c.mock_with :rspec
end

require 'puppetlabs_spec_helper/module_spec_helper'
require 'rspec-puppet-facts'

require 'spec_helper_local' if File.file?(File.join(File.dirname(__FILE__), 'spec_helper_local.rb'))

include RspecPuppetFacts

default_facts = {
  puppetversion: Puppet.version,
  facterversion: Facter.version,
}

default_fact_files = [
  File.expand_path(File.join(File.dirname(__FILE__), 'default_facts.yml')),
  File.expand_path(File.join(File.dirname(__FILE__), 'default_module_facts.yml')),
]

default_fact_files.each do |f|
  next unless File.exist?(f) && File.readable?(f) && File.size?(f)

  begin
    require 'deep_merge'
    default_facts.deep_merge!(YAML.safe_load_file(f, permitted_classes: [], permitted_symbols: [], aliases: true))
  rescue StandardError => e
    RSpec.configuration.reporter.message "WARNING: Unable to load #{f}: #{e}"
  end
end

# read default_facts and merge them over what is provided by facterdb
default_facts.each do |fact, value|
  add_custom_fact fact, value, merge_facts: true
end

RSpec.configure do |c|
  c.default_facts = default_facts
  c.hiera_config = File.expand_path(File.join(__FILE__, '../fixtures/hiera.yaml'))
  c.before :each do
    # set to strictest setting for testing
    # by default Puppet runs at warning level
    Puppet.settings[:strict] = :warning
    Puppet.settings[:strict_variables] = true
  end
  c.filter_run_excluding(bolt: true) unless ENV['GEM_BOLT']
  c.after(:suite) do
    RSpec::Puppet::Coverage.report!(0)
  end

  # Filter backtrace noise
  backtrace_exclusion_patterns = [
    %r{spec_helper},
    %r{gems},
  ]

  if c.respond_to?(:backtrace_exclusion_patterns)
    c.backtrace_exclusion_patterns = backtrace_exclusion_patterns
  elsif c.respond_to?(:backtrace_clean_patterns)
    c.backtrace_clean_patterns = backtrace_exclusion_patterns
  end
end

# Ensures that a module is defined
# @param module_name Name of the module
def ensure_module_defined(module_name)
  module_name.split('::').reduce(Object) do |last_module, next_module|
    last_module.const_set(next_module, Module.new) unless last_module.const_defined?(next_module, false)
    last_module.const_get(next_module, false)
  end
end

# 'spec_overrides' from sync.yml will appear below this line
require 'fileutils'
require 'json'

def self_fixture_module_name
  JSON.parse(File.read(File.expand_path('../metadata.json', __dir__)))['name'].split('-').last
end

def prepare_filtered_self_fixture
  return @prepared_filtered_self_fixture if @prepared_filtered_self_fixture

  repo_root = File.expand_path('..', __dir__)
  fixtures_root = File.expand_path('fixtures', __dir__)
  filtered_modules_root = File.join(fixtures_root, 'self_modules', Process.pid.to_s)
  filtered_module_root = File.join(filtered_modules_root, self_fixture_module_name)

  # Puppet treats .resource_types/*.pp as manifests when the module
  # fixture is a plain symlink to the repo root. Build a minimal self
  # fixture that only exposes real module content so rspec-puppet ignores
  # generated Bolt stubs.
  module_entries = [
    'data',
    'environment.conf',
    'files',
    'functions',
    'hiera.yaml',
    'lib',
    'manifests',
    'metadata.json',
    'plans',
    'site.pp',
    'tasks',
    'templates',
    'types',
  ]

  FileUtils.mkdir_p(filtered_module_root)

  module_entries.each do |entry|
    source = File.join(repo_root, entry)
    target = File.join(filtered_module_root, entry)
    next unless File.exist?(source)

    FileUtils.ln_sf(source, target)
  end

  at_exit do
    FileUtils.rm_rf(filtered_modules_root) if File.directory?(filtered_modules_root)
  end

  @prepared_filtered_self_fixture = filtered_modules_root
end

RSpec.configure do |c|
  c.module_path = [
    prepare_filtered_self_fixture,
    File.expand_path(File.join(__dir__, 'fixtures', 'modules')),
  ].join(File::PATH_SEPARATOR)
end
