#!/usr/bin/env ruby
# frozen_string_literal: true

require_relative 'puppet-compiler-snapshot'

# Identity-keyed publication and static retention, not a mutable current pointer.
# The caller supplies the accepted expectation; this module never mints one.
module NestPuppetCompilerStore
  def self.read_receipt(path)
    File.open(path, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |file|
      NestPuppetVersionedCode.check(file.stat.file? && file.stat.size <= 16_384)
      JSON.parse(file.read(16_385))
    end
  end

  def self.release_path(store, identity)
    NestPuppetVersionedCode.check(identity.is_a?(String) && %r{\Asha256:[0-9a-f]{64}\z}.match?(identity))
    File.join(store, identity.delete_prefix('sha256:'))
  end

  def self.snapshot(store, identity, readonly: NestPuppetVersionedCode.method(:read_only?))
    path = release_path(store, identity)
    NestPuppetVersionedCode.check(File.realpath(path) == path)
    expected = read_receipt(File.join(path, 'expected.json'))
    NestPuppetVersionedCode.check(expected.is_a?(Hash) && expected['code_id'] == identity)
    root = File.join(path, 'main')
    NestPuppetVersionedCode.check(File.realpath(root) == root)
    NestPuppetVersionedCode::Snapshot.new(root, expected, readonly: readonly)
  end

  def self.sync_tree(root)
    # Durability before rename: do not publish a receipt ahead of copied bytes.
    Find.find(root) do |path|
      stat = File.lstat(path)
      next if stat.symlink?
      File.open(path, File::RDONLY | File::NOFOLLOW | File::NONBLOCK, &:fsync)
    end
  end

  def self.publish(source, store, expected)
    NestPuppetVersionedCode.check(File.realpath(store) == store)
    stat = File.lstat(store)
    NestPuppetVersionedCode.check(stat.directory? && stat.uid == Process.euid && stat.mode.nobits?(0o077))
    NestPuppetVersionedCode.check(expected.is_a?(Hash) && expected.keys.sort == ['code_id', 'environment', 'schema', 'source'])
    NestPuppetVersionedCode.check(expected['schema'].instance_of?(Integer) && expected['schema'] == 1 && expected['environment'] == 'main')
    NestPuppetVersionedCode.check(expected['source'].is_a?(String) && %r{\A[0-9a-f]{40}\z}.match?(expected['source']))
    path = release_path(store, expected['code_id'])
    # The private store has one publisher. Never unlink/recreate this lock.
    File.open(File.join(store, '.publish.lock'), File::RDWR | File::CREAT | File::NOFOLLOW | File::NONBLOCK, 0o600) do |lock|
      NestPuppetVersionedCode.check(lock.stat.file? && lock.stat.uid == Process.euid && lock.stat.mode.nobits?(0o077))
      NestPuppetVersionedCode.check(lock.flock(File::LOCK_EX | File::LOCK_NB))
      if File.exist?(path) || File.symlink?(path)
        NestPuppetVersionedCode.check(File.realpath(path) == path)
        NestPuppetVersionedCode.check(read_receipt(File.join(path, 'expected.json')) == expected)
      else
        # An interrupted publication is diagnostic state, not permission to
        # clean/adopt/retry. Exclusive mkdir refuses its retained pending tree.
        pending = path + '.pending'
        Dir.mkdir(pending, 0o700)
        NestPuppetCompilerSnapshot.prepare(source, File.join(pending, 'main'), expected)
        File.open(File.join(pending, 'expected.json'), File::WRONLY | File::CREAT | File::EXCL | File::NOFOLLOW, 0o600) do |receipt|
          receipt.write(JSON.generate(expected, ascii_only: true) + "\n")
          receipt.fsync
        end
        sync_tree(pending)
        File.rename(pending, path)
        File.open(store, File::RDONLY, &:fsync)
      end
      snapshot(store, expected['code_id'], readonly: ->(_root) { true })
    end
    { 'schema' => 1, 'kind' => 'nest_puppet_compiler_publication', 'source' => expected['source'],
      'code_id' => expected['code_id'], 'published' => true, 'compiler_attestation' => false }
  end

  def self.main(args)
    mode, *native = args
    if mode == 'publish'
      NestPuppetVersionedCode.check(native.length == 3)
      source, store, receipt = native
      puts JSON.generate(publish(source, store, read_receipt(receipt)))
    elsif mode == 'content'
      NestPuppetVersionedCode.check(native.length == 4)
      store, environment, identity, path = native
      NestPuppetVersionedCode.check(File.realpath(store) == store && NestPuppetVersionedCode.read_only?(store))
      snapshot(store, identity).content(environment, identity, path) do |file|
        $stdout.binmode
        IO.copy_stream(file, $stdout)
      end
    else
      NestPuppetVersionedCode.check(false)
    end
    0
  rescue NestPuppetVersionedCode::Unavailable, SystemCallError, IOError, JSON::ParserError, ArgumentError, TypeError
    warn 'Compiler snapshot store unavailable'
    1
  end
end

exit NestPuppetCompilerStore.main(ARGV) if $PROGRAM_NAME == __FILE__
