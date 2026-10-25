#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'tmpdir'
require 'open3'

# Transport the collector's bounded evidence to the EXISTING native validator.
# Do not weaken its lock, identity checks or accepted-evidence idempotence.
module NestUpdateAccept
  def self.run(params, directory: '/var/lib/nest/updates', runner: Open3.method(:capture3))
    raise 'Invalid acceptance parameters' unless params.keys.reject { |key| key.start_with?('_') }.sort == ['evidence', 'transaction'] &&
                                                 params['_noop'] != true && params['transaction'].is_a?(String) &&
                                                 params['transaction'].match?(%r{\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\z}) && params['evidence'].is_a?(Hash)

    evidence = JSON.generate(params['evidence'])
    raise 'Evidence exceeds native limit' if evidence.bytesize > 65_536

    Dir.mktmpdir('accept-', directory) do |dir|
      path = File.join(dir, 'evidence.json')
      File.open(path, File::WRONLY | File::CREAT | File::EXCL, 0o600) do |file|
        file.write(evidence)
        file.flush
        file.fsync
      end
      stdout, _stderr, status = runner.call('nest', 'reset', 'accept', params['transaction'], '--evidence', path, '--format=json')
      raise 'Native acceptance failed; observe before retry' unless status.success?

      report = JSON.parse(stdout)
      complete = report['kind'] == 'reset_transaction_report' && report['accepted'] == true &&
                 report['id'] == params['transaction'] && report['acceptance']['evidence'] == params['evidence']
      raise 'Native acceptance did not complete' unless complete

      { 'accepted' => true }
    end
  end

  def self.main
    raise 'Root required' unless Process.euid.zero?

    raw = $stdin.read(131_073)
    raise 'Parameter limit' if raw.bytesize > 131_072

    puts JSON.generate(run(JSON.parse(raw)))
    0
  rescue StandardError
    puts JSON.generate('_error' => { 'kind' => 'nest/update-accept', 'msg' => 'Native acceptance failed; inspect existing state, never reset or reboot' })
    1
  end
end

exit NestUpdateAccept.main if __FILE__ == $PROGRAM_NAME
