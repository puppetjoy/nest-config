# frozen_string_literal: true

# Disposable native HTTP probe for the exact rendered compiler store. No agent
# runs and no catalog, private module payload or server log leaves the container.
require 'digest'
require 'fileutils'
require 'json'
require 'net/http'
require 'open3'
require 'timeout'

current = JSON.parse(ARGV.fetch(0))
receipts = JSON.parse(ARGV.fetch(1))
jar = '/opt/puppetlabs/server/apps/puppetserver/puppet-server-release.jar'
raise 'Wrong native server JAR' unless Digest::SHA256.file(jar).hexdigest == ARGV.fetch(2)
root = '/compiler/store/' + current.fetch('code_id').delete_prefix('sha256:')
_output, status = Open3.capture2e('/compiler/runtime/entrypoint')
raise 'Rendered startup failed' unless status.success?
FileUtils.mkdir_p(['/work/conf.d', '/work/conf'])
FileUtils.cp('/etc/puppetlabs/puppet/puppet.conf', '/work/conf/puppet.conf')
# Only local runtime paths differ from the deployed compiler; immutable module
# and environment paths and both rendered native wrappers remain unchanged.
{
  'certname' => 'offline-compiler.nest', 'vardir' => '/work/var',
  'logdir' => '/work/log', 'rundir' => '/work/run', 'ssldir' => '/work/ssl',
  'cadir' => '/work/ca', 'settings_catalog' => 'false', 'node_terminus' => 'plain',
  'reports' => 'store', 'environment_timeout' => '0',
}.each do |name, value|
  _out, set_status = Open3.capture2e('puppet', 'config', 'set', name, value, '--confdir', '/work/conf', '--section', 'server')
  raise 'Offline server configuration failed' unless set_status.success?
end
load_paths = [
  '/opt/puppetlabs/puppet/lib/ruby/vendor_ruby',
  '/opt/puppetlabs/puppet/lib/ruby/gems/3.2.0/gems/concurrent-ruby-1.2.3/lib/concurrent-ruby',
] + Dir['/opt/puppetlabs/puppet/lib/ruby/vendor_gems/gems/*/lib']
config = <<~CONF
  jruby-puppet: {
    ruby-load-path: #{JSON.generate(load_paths)}
    gem-home: /work/gems
    master-conf-dir: /work/conf
    master-code-dir: #{root}
    master-var-dir: /work/var
    master-log-dir: /work/log
    master-run-dir: /work/run
    max-active-instances: 1
  }
  webserver: { host: "127.0.0.1", port: 8140 }
  web-router-service: {
    "puppetlabs.services.ca.certificate-authority-service/certificate-authority-service": "/puppet-ca"
    "puppetlabs.services.master.master-service/master-service": "/puppet"
    "puppetlabs.services.puppet-admin.puppet-admin-service/puppet-admin-service": "/puppet-admin-api"
    "puppetlabs.trapperkeeper.services.status.status-service/status-service": "/status"
    "puppetlabs.trapperkeeper.services.metrics.metrics-service/metrics-webservice": "/metrics"
  }
  authorization: {
    version: 1
    rules: [{ match-request: { path: "/", type: path }, allow-unauthenticated: true, sort-order: 1, name: "Offline loopback probe only" }]
  }
  metrics: { server-id: "offline-compiler.nest" }
CONF
File.write('/work/conf.d/server.conf', config)
FileUtils.cp('/compiler/runtime/versioned-code.conf', '/work/conf.d/versioned-code.conf')
bootstrap = File.read('/opt/puppetlabs/server/apps/puppetserver/config/services.d/bootstrap.cfg')
bootstrap += "\npuppetlabs.services.ca.certificate-authority-service/certificate-authority-service\n"
bootstrap += "puppetlabs.trapperkeeper.services.watcher.filesystem-watch-service/filesystem-watch-service\n"
File.write('/work/bootstrap.cfg', bootstrap)
FileUtils.chown_R(999, 999, '/work')
Process::GID.change_privilege(999)
Process::UID.change_privilege(999)
log = File.open('/work/server.log', 'w')
pid = Process.spawn('java', '-Xmx1500m', '-Djava.io.tmpdir=/work', '-cp', jar, 'clojure.main', '-m', 'puppetlabs.trapperkeeper.main',
                    '--config', '/work/conf.d', '--bootstrap-config', '/work/bootstrap.cfg', out: log, err: log)
def get_response(uri)
  Net::HTTP.start(uri.host, uri.port, open_timeout: 5, read_timeout: 30) { |http| http.get(uri.request_uri) }
end

begin
  deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + 210
  loop do
    raise 'Native server exited during startup' if Process.waitpid(pid, Process::WNOHANG)
    raise 'Native server readiness deadline expired' if Process.clock_gettime(Process::CLOCK_MONOTONIC) > deadline
    begin
      break if get_response(URI('http://127.0.0.1:8140/status/v1/simple')).code == '200'
    rescue Errno::ECONNREFUSED, EOFError
      # The readiness deadline bounds this loop; no production endpoint is used.
    end
    sleep 1
  end
  paths = ['.modules/nest/files/puppet-versioned-code.rb', '.modules/nest/lib/puppet/functions/nest/openvox_compiler_patches.rb']
  rows = receipts.map do |receipt|
    identity = receipt.fetch('code_id')
    contents = paths.map do |path|
      local_path = '/compiler/store/' + identity.delete_prefix('sha256:') + '/main/' + path
      query = URI.encode_www_form('environment' => 'main', 'code_id' => identity)
      response = get_response(URI('http://127.0.0.1:8140/puppet/v3/static_file_content/' + path + '?' + query))
      if File.file?(local_path)
        bytes = File.binread(local_path)
        raise 'Native retained static content mismatch' unless response.code == '200' && response.body.b == bytes
        { 'path' => path, 'sha256' => Digest::SHA256.hexdigest(bytes), 'http_status' => response.code }
      else
        raise 'Missing retained file did not refuse' unless response.code.to_i >= 400
        { 'path' => path, 'sha256' => nil, 'http_status' => response.code }
      end
    end
    { 'code_id' => identity, 'contents' => contents }
  end
  # A cached pre-adoption catalog with no code_id still uses the normal v3
  # file-content endpoint. Verify compatibility separately from versioned reads.
  legacy = get_response(URI('http://127.0.0.1:8140/puppet/v3/file_content/modules/nest/puppet-versioned-code.rb?environment=main'))
  raise 'Legacy file-content route mismatch' unless legacy.code == '200' && Digest::SHA256.hexdigest(legacy.body) == rows.last.fetch('contents').first.fetch('sha256')
  wrong_query = URI.encode_www_form('environment' => 'main', 'code_id' => 'sha256:' + '0' * 64)
  wrong = get_response(URI('http://127.0.0.1:8140/puppet/v3/static_file_content/' + paths.first + '?' + wrong_query))
  raise 'Unknown identity accepted' unless wrong.code.to_i >= 400
  # Use the real immutable main manifest's explicit forbidden client, avoiding
  # host facts, private decryption keys and any application catalog payload.
  request = { 'certname' => 'bolt', 'environment' => 'main', 'facts' => { 'values' => {} },
              'trusted_facts' => { 'values' => { 'authenticated' => 'remote', 'certname' => 'bolt', 'hostname' => 'bolt', 'domain' => '' } },
              'persistence' => { 'facts' => false, 'catalog' => false },
              'options' => { 'prefer_requested_environment' => true } }
  uri = URI('http://127.0.0.1:8140/puppet/v4/catalog')
  req = Net::HTTP::Post.new(uri, { 'Content-Type' => 'application/json', 'Accept' => 'application/json' })
  req.body = JSON.generate(request)
  refusal = Net::HTTP.start(uri.host, uri.port, read_timeout: 90) { |http| http.request(req) }
  raise 'Immutable main manifest refusal not observed (HTTP ' + refusal.code + ')' unless refusal.code.to_i >= 400 && refusal.body.include?('bolt is not allowed to use Puppet')
  puts JSON.generate('native_http_dispatch' => true, 'uid' => Process.euid, 'static_content' => rows,
                     'distinct_retained_content_verified' => rows.map { |row| row.fetch('contents').last.fetch('sha256') }.uniq.length > 1,
                     'legacy_null_code_id_route_verified' => true, 'wrong_identity_refused' => true,
                     'immutable_main_manifest_refusal_verified' => true, 'catalog_success' => false,
                     'host_cache_coverage' => false, 'compiler_attestation' => false, 'catalog_applied' => false)
ensure
  begin
    Process.kill('TERM', pid)
  rescue Errno::ESRCH
    # The startup liveness check may already have reaped the child.
  end
  begin
    Timeout.timeout(15) { Process.waitpid(pid) }
  rescue Timeout::Error
    begin
      Process.kill('KILL', pid)
    rescue Errno::ESRCH
      # The child exited between the timeout and signal.
    end
    begin
      Process.waitpid(pid)
    rescue Errno::ECHILD
      # Another liveness observation already reaped the child.
    end
  rescue Errno::ECHILD
    # The startup liveness check may already have reaped the child.
  end
  log.close
end
