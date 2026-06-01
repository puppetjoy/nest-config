# frozen_string_literal: true

require_relative 'plugins/check_parameter_list_alignment'

# Shared PuppetLint policy used by both generated Rake tasks and PDK.
module NestPuppetLintConfig
  DISABLED_CHECKS = [
    'arrow_on_right_operand_line',
    'autoloader_layout',
    'case_without_default',
    'documentation',
    'manifest_whitespace_closing_bracket_after',
    'manifest_whitespace_opening_brace_before',
    'manifest_whitespace_two_empty_lines',
    'nested_classes_or_defines',
    'parameter_documentation',
    'strict_indent',
    'variable_scope',
  ].freeze

  def self.apply
    DISABLED_CHECKS.each do |check|
      PuppetLint.configuration.send("disable_#{check}")
    end
  end
end

NestPuppetLintConfig.apply
