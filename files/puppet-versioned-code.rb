#!/usr/bin/env ruby
# frozen_string_literal: true

require 'digest'
require 'find'
require 'json'

# Native code-ID/content hooks for an independently expected, isolated compiler
# snapshot. A read-only view of the shared r10k tree is NOT an isolated snapshot.
module NestPuppetVersionedCode
  class Unavailable < StandardError; end

  def self.check(value)
    raise Unavailable, 'Compiler snapshot identity unavailable' unless value
  end

  def self.inventory(root)
    root = File.realpath(root)
    rows = []
    Find.find(root) do |path|
      next if path == root
      if File.basename(path) == '.git'
        Find.prune if File.directory?(path)
        next
      end
      stat = File.lstat(path)
      name = path.delete_prefix(root + '/')
      check(name.valid_encoding? && !name.match?(%r{[\x00-\x1f\x7f]}))
      row = if stat.symlink?
              # A retained missing leaf (for example an unavailable firmware
              # alias) is still an input identity, not permission to serve it.
              # Resolve parent links fully and allow only that final missing
              # component. Static content still requires realpath below.
              target = File.realdirpath(path)
              check(target.start_with?(root + '/'))
              [name, 'link', File.readlink(path)]
            elsif stat.directory?
              [name, 'directory', stat.mode & 0o7777]
            elsif stat.file?
              [name, 'file', stat.mode & 0o7777, Digest::SHA256.file(path).hexdigest]
            else
              raise Unavailable, 'Unsupported compiler snapshot entry'
            end
      rows << row
    end
    check(!rows.empty?)
    rows.sort
  end

  def self.code_id(rows)
    'sha256:' + Digest::SHA256.hexdigest(JSON.generate(rows, ascii_only: true) + "\n")
  end

  def self.read_only?(root, mountinfo = File.read('/proc/self/mountinfo'))
    # Select the most specific mount, not an ancestor's read-only flag.
    mounts = mountinfo.lines.map do |line|
      fields = line.split
      next unless fields.length >= 10 && fields.include?('-')
      path = fields[4].gsub(%r{\\([0-7]{3})}) { Regexp.last_match(1).to_i(8).chr }
      next unless root == path || root.start_with?((path == '/') ? '/' : path + '/')
      [path.length, fields[5].split(',').include?('ro')]
    end
    mounts.compact!
    !mounts.empty? && mounts.max_by(&:first)[1]
  end

  # Validate a frozen environment against a separately supplied release receipt.
  class Snapshot
    def initialize(root, expected, readonly: NestPuppetVersionedCode.method(:read_only?))
      @root = File.realpath(root)
      NestPuppetVersionedCode.check(readonly.call(@root))
      NestPuppetVersionedCode.check(expected.is_a?(Hash) && expected.keys.sort == ['code_id', 'environment', 'schema', 'source'])
      NestPuppetVersionedCode.check(expected['schema'] == 1 && expected['environment'] == 'main')
      NestPuppetVersionedCode.check(expected['source'].is_a?(String) && %r{\A[0-9a-f]{40}\z}.match?(expected['source']))
      NestPuppetVersionedCode.check(expected['code_id'].is_a?(String) && %r{\Asha256:[0-9a-f]{64}\z}.match?(expected['code_id']))
      @expected = expected.dup.freeze
      # Snapshot publication replaces the mutable Git command with this exact
      # constant. Refuse module/manifest paths outside the isolated snapshot.
      config = File.read(File.join(@root, 'environment.conf'), 4097)
      NestPuppetVersionedCode.check(config.bytesize <= 4096)
      lines = config.lines.map(&:strip).reject { |line| line.empty? || line.start_with?('#') }
      required = ["config_version = /bin/echo #{@expected['source']}", 'manifest = manifests', 'modulepath = modules:.modules']
      NestPuppetVersionedCode.check(lines.sort == required.sort)
      # Hash the actual frozen tree, not a mutable current pointer or Git SHA.
      NestPuppetVersionedCode.check(NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(@root)) == @expected['code_id'])
    end

    def id(environment)
      NestPuppetVersionedCode.check(environment == @expected['environment'])
      @expected['code_id']
    end

    def content(environment, identity, path)
      NestPuppetVersionedCode.check(identity == id(environment))
      # Match the native static-file API boundary; never expose data or .git.
      match = %r{\A((?:modules|\.modules)/[a-z][a-z0-9_]*/(?:files|lib|scripts|tasks))/([A-Za-z0-9_./-]+)\z}.match(path)
      NestPuppetVersionedCode.check(match && path.split('/').none? { |part| ['.', '..', ''].include?(part) })
      allowed = File.realpath(File.join(@root, match[1]))
      target = File.realpath(File.join(@root, path))
      NestPuppetVersionedCode.check(allowed.start_with?(@root + '/') && target.start_with?(allowed + '/'))
      File.open(target, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |file|
        NestPuppetVersionedCode.check(file.stat.file?)
        yield file
      end
    end
  end

  def self.main(args)
    mode, root, receipt, *native = args
    check(['id', 'content'].include?(mode) && root && receipt && native.length == ((mode == 'id') ? 1 : 3))
    expected = JSON.parse(File.read(receipt, 16_385))
    snapshot = Snapshot.new(root, expected)
    if mode == 'id'
      puts snapshot.id(native[0])
    else
      snapshot.content(*native) do |file|
        $stdout.binmode
        IO.copy_stream(file, $stdout)
      end
    end
    0
  rescue Unavailable, SystemCallError, IOError, JSON::ParserError, ArgumentError
    warn 'Compiler snapshot identity unavailable'
    1
  end
end

exit NestPuppetVersionedCode.main(ARGV) if $PROGRAM_NAME == __FILE__
