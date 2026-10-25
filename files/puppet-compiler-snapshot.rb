#!/usr/bin/env ruby
# frozen_string_literal: true

require_relative 'puppet-versioned-code'

# Init-container copy boundary only. The compiler must subsequently mount this
# pod-private volume read-only; this helper never reconfigures a running server.
module NestPuppetCompilerSnapshot
  def self.prepare(source, destination, expected)
    NestPuppetVersionedCode.check(expected.is_a?(Hash) && expected.keys.sort == ['code_id', 'environment', 'schema', 'source'])
    NestPuppetVersionedCode.check(expected['schema'].instance_of?(Integer) && expected['schema'] == 1 && expected['environment'] == 'main')
    NestPuppetVersionedCode.check(expected['source'].is_a?(String) && %r{\A[0-9a-f]{40}\z}.match?(expected['source']))
    NestPuppetVersionedCode.check(expected['code_id'].is_a?(String) && %r{\Asha256:[0-9a-f]{64}\z}.match?(expected['code_id']))
    source = File.realpath(source)
    parent = File.dirname(destination)
    NestPuppetVersionedCode.check(destination.start_with?('/') && File.realpath(parent) == parent)
    NestPuppetVersionedCode.check(!['.', '..', ''].include?(File.basename(destination)))
    stat = File.lstat(parent)
    NestPuppetVersionedCode.check(stat.directory? && stat.uid == Process.euid && stat.mode.nobits?(0o022))
    NestPuppetVersionedCode.check(destination != source && !destination.start_with?(source + '/') && !source.start_with?(destination + '/'))
    rows = NestPuppetVersionedCode.inventory(source)
    config = rows.find { |row| row[0] == 'environment.conf' }
    NestPuppetVersionedCode.check(config && config[1] == 'file')
    # A relative contained link survives relocation; an absolute source link
    # would still point at the mutable input even if it was originally contained.
    NestPuppetVersionedCode.check(rows.none? { |row| row[1] == 'link' && row[2].start_with?('/') })
    Dir.mkdir(destination, 0o755) # Exclusive; never adopt, replace or clean a tree.
    rows.each do |row|
      name, kind, mode = row
      target = File.join(destination, name)
      case kind
      when 'directory'
        Dir.mkdir(target, 0o700)
      when 'link'
        File.symlink(mode, target)
      when 'file'
        File.open(target, File::WRONLY | File::CREAT | File::EXCL | File::NOFOLLOW, 0o600) do |output|
          if name == 'environment.conf'
            output.write("modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo #{expected['source']}\n")
          else
            File.open(File.join(source, name), File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |input|
              NestPuppetVersionedCode.check(input.stat.file?)
              IO.copy_stream(input, output)
            end
          end
          output.chmod(mode)
        end
      end
    end
    rows.reverse_each { |row| File.chmod(row[2], File.join(destination, row[0])) if row[1] == 'directory' }
    # The init container is the only writer. Validate the completed copy, not
    # the input's Git metadata or a read-only view of its mutable backing store.
    snapshot = NestPuppetVersionedCode::Snapshot.new(destination, expected, readonly: ->(_path) { true })
    { 'schema' => 1, 'kind' => 'nest_puppet_compiler_snapshot', 'source' => expected['source'],
      'code_id' => snapshot.id('main'), 'copied' => true, 'compiler_read_only_verified' => false,
      'compiler_attestation' => false }
  end

  def self.main(args)
    NestPuppetVersionedCode.check(args.length == 3)
    source, destination, receipt = args
    expected = File.open(receipt, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |file|
      NestPuppetVersionedCode.check(file.stat.file? && file.stat.size <= 16_384)
      JSON.parse(file.read(16_385))
    end
    puts JSON.generate(prepare(source, destination, expected))
    0
  rescue NestPuppetVersionedCode::Unavailable, SystemCallError, IOError, JSON::ParserError, ArgumentError
    warn 'Compiler snapshot publication unavailable'
    1
  end
end

exit NestPuppetCompilerSnapshot.main(ARGV) if $PROGRAM_NAME == __FILE__
