# frozen_string_literal: true

PuppetLint.new_check(:parameter_list_alignment) do
  DECLARATION_START = %r{^\s*(class|define|plan)\b.*\(\s*(?:#.*)?$}
  DECLARATION_END = %r{^\s*\)\s*(?:inherits\s+\S+\s*)?\{}
  DEFAULTED_PARAMETER = %r{\$[A-Za-z_][A-Za-z0-9_]*.*\s=\s}
  PARAMETER_VARIABLE = %r{\$[A-Za-z_][A-Za-z0-9_]*}
  DEFAULT_EQUALS = %r{\s=\s}

  def check
    parameter_lists.each do |parameter_list|
      parameter_groups(parameter_list).each do |parameter_group|
        defaulted_lines = parameter_group.select { |entry| entry[:text].match?(DEFAULTED_PARAMETER) }
        check_variable_alignment(defaulted_lines)
        check_default_alignment(defaulted_lines)
      end
    end
  end

  private

  def parameter_lists
    lists = []
    current = nil

    manifest_lines.each_with_index do |line, index|
      if current
        if line.match?(DECLARATION_END)
          lists << current
          current = nil
        else
          current << { line: index + 1, text: line }
        end
      elsif line.match?(DECLARATION_START)
        current = []
      end
    end

    lists
  end

  def parameter_groups(parameter_list)
    groups = []
    current = []

    parameter_list.each do |entry|
      if parameter_line?(entry)
        current << entry
      elsif current.any?
        groups << current
        current = []
      end
    end

    groups << current if current.any?
    groups
  end

  def parameter_line?(entry)
    entry[:text].lstrip.start_with?('$') || entry[:text].match?(PARAMETER_VARIABLE)
  end

  def check_variable_alignment(defaulted_lines)
    columns = defaulted_lines.map { |entry| entry[:text].index('$') }.compact
    return if columns.length < 2

    expected_column = dominant_column(columns)

    defaulted_lines.each do |entry|
      actual_column = entry[:text].index('$')
      next if actual_column == expected_column

      notify(
        :warning,
        {
          message: "defaulted parameter variable should be aligned to column #{expected_column + 1}",
          line: entry[:line],
          column: actual_column + 1,
        },
      )
    end
  end

  def check_default_alignment(defaulted_lines)
    columns = defaulted_lines.map { |entry| entry[:text].index(DEFAULT_EQUALS) + 2 }
    return if columns.length < 2

    expected_column = dominant_column(columns)

    defaulted_lines.each do |entry|
      actual_column = entry[:text].index(DEFAULT_EQUALS) + 2
      next if actual_column == expected_column

      notify(
        :warning,
        {
          message: "parameter default equals sign should be aligned to column #{expected_column + 1}",
          line: entry[:line],
          column: actual_column + 1,
        },
      )
    end
  end

  def dominant_column(columns)
    columns
      .tally
      .sort_by { |column, count| [-count, -column] }
      .first
      .first
  end
end
