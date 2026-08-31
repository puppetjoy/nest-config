#!/usr/bin/ruby
# frozen_string_literal: true

require 'tempfile'

check_only = ARGV.delete('--check')
path = ARGV.shift

if path.nil? || !ARGV.empty?
  warn "usage: #{File.basename($PROGRAM_NAME)} [--check] PATH"
  exit 2
end

unless File.file?(path)
  warn "#{path}: not a regular file"
  exit 2
end

lines = File.readlines(path)
anchor = %r{^\s*NVreg_PreserveVideoMemoryAllocations=1 \\\s*$}
threshold = %r{^\s*NVreg_S0ixPowerManagementVideoMemoryThreshold=}
valid_positions = lines.each_index.select { |index| lines[index].match?(anchor) }.map { |index| index + 1 }
misplaced_positions = lines.each_index.select do |index|
  lines[index].match?(threshold) && !valid_positions.include?(index)
end

if check_only
  exit(misplaced_positions.empty? ? 1 : 0)
end

exit 0 if misplaced_positions.empty?

stat = File.stat(path)
directory = File.dirname(path)
Tempfile.create(['.nvidia.conf.', '.tmp'], directory) do |temporary|
  lines.each_with_index do |line, index|
    temporary.write(line) unless misplaced_positions.include?(index)
  end
  temporary.flush
  temporary.fsync
  File.chmod(stat.mode & 0o7777, temporary.path)
  File.chown(stat.uid, stat.gid, temporary.path)
  File.rename(temporary.path, path)
end
