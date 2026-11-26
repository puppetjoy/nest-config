# frozen_string_literal: true

# Diagnostic only: log paths, counts and durations, not example descriptions.
class PdkFileTimingDiagnostic
  RSpec::Core::Formatters.register self, :example_passed, :example_failed, :example_pending, :dump_summary

  def initialize(output)
    @output = output
    @files = Hash.new { |files, path| files[path] = [0, 0.0] }
  end

  def example_passed(notification)
    example = notification.example
    path = example.example_group.parent_groups.last.metadata.fetch(:file_path)
    return unless path.match?(%r{\A(?:\./)?spec/[a-zA-Z0-9_./-]+_spec\.rb\z})

    row = @files[path.sub(%r{\A\./}, '')]
    row[0] += 1
    row[1] += example.execution_result.run_time
  end
  alias example_failed example_passed
  alias example_pending example_passed

  def dump_summary(notification)
    @output.puts('PDK_WORKER_TIMING %d %.6f' % [notification.example_count, notification.duration])
    @files.sort.each do |path, (count, elapsed)|
      @output.puts('PDK_FILE_TIMING %s %d %.6f' % [path, count, elapsed])
    end
  end
end
