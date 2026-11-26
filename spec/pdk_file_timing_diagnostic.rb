# frozen_string_literal: true

# Diagnostic only: log paths, counts and durations, not example descriptions.
class PdkFileTimingDiagnostic
  RSpec::Core::Formatters.register self, :start, :example_started, :example_finished, :stop, :dump_summary

  def initialize(output)
    @output = output
    @files = Hash.new { |files, path| files[path] = [0, 0.0] }
    @elapsed = 0.0
  end

  def start(_notification)
    @started = clock
  end

  def example_started(notification)
    now = clock
    @first ||= now
    if @last && now - @last >= 1
      next_example = label(notification.example)
      @output.puts('PDK_EXAMPLE_GAP %.6f %s %s' % [now - @last, @previous_example, next_example])
    end
  end

  def example_finished(notification)
    @last = clock
    example = notification.example
    @previous_example = label(example)
    row = @files[owner(example)]
    elapsed = example.execution_result.run_time
    row[0] += 1
    row[1] += elapsed
    @elapsed += elapsed
  end

  def stop(_notification)
    @stopped = clock
  end

  def dump_summary(notification)
    if @first && @last
      phases = [notification.example_count, @first - @started, @last - @first, @stopped - @last, @elapsed]
      @output.puts('PDK_PHASE_TIMING %d %.6f %.6f %.6f %.6f' % phases)
    end
    @files.sort.each do |path, (count, elapsed)|
      @output.puts('PDK_FILE_TIMING %s %d %.6f' % [path, count, elapsed])
    end
  end

  private

  def owner(example)
    path = example.example_group.parent_groups.last.metadata.fetch(:file_path)
    path.match?(%r{\A(?:\./)?spec/[a-zA-Z0-9_./-]+_spec\.rb\z}) ? path.sub(%r{\A\./}, '') : 'unattributed'
  end

  def label(example)
    '%s:%d' % [owner(example), example.metadata.fetch(:line_number)]
  end

  def clock
    Process.clock_gettime(Process::CLOCK_MONOTONIC)
  end
end
