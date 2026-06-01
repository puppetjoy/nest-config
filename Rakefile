# frozen_string_literal: true

require 'bundler'
require 'puppet_litmus/rake_tasks' if Gem.loaded_specs.key? 'puppet_litmus'
require 'puppetlabs_spec_helper/rake_tasks'
require 'puppet-syntax/tasks/puppet-syntax'
require 'puppet-strings/tasks' if Gem.loaded_specs.key? 'puppet-strings'
require './lib/puppet-lint/plugins/check_parameter_list_alignment'

PuppetLint.configuration.send('disable_relative')
PuppetLint.configuration.send('disable_80chars')
PuppetLint.configuration.send('disable_140chars')
PuppetLint.configuration.send('disable_class_inherits_from_params_class')
PuppetLint.configuration.send('disable_autoloader_layout')
PuppetLint.configuration.send('disable_documentation')
PuppetLint.configuration.send('disable_single_quote_string_with_variables')
PuppetLint.configuration.send('disable_arrow_on_right_operand_line')
PuppetLint.configuration.send('disable_autoloader_layout')
PuppetLint.configuration.send('disable_case_without_default')
PuppetLint.configuration.send('disable_documentation')
PuppetLint.configuration.send('disable_manifest_whitespace_closing_bracket_after')
PuppetLint.configuration.send('disable_manifest_whitespace_opening_brace_before')
PuppetLint.configuration.send('disable_manifest_whitespace_two_empty_lines')
PuppetLint.configuration.send('disable_nested_classes_or_defines')
PuppetLint.configuration.send('disable_parameter_documentation')
PuppetLint.configuration.send('disable_strict_indent')
PuppetLint.configuration.send('disable_variable_scope')
PuppetLint.configuration.fail_on_warnings = true
PuppetLint.configuration.ignore_paths = [".vendor/**/*.pp", ".bundle/**/*.pp", "pkg/**/*.pp", "spec/**/*.pp", "tests/**/*.pp", "types/**/*.pp", "vendor/**/*.pp"]

