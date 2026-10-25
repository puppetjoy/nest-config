"""Offline native Puppetserver contract test; requires Podman and a pinned image.

Generated fixture code is public/inert. No production config or agent is read.
Only this test's generated directory and the source helper are mounted read-only.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--image', required=True)
parser.add_argument('--jar-sha256', required=True)
parser.add_argument('--output-dir', required=True, type=Path)
options = parser.parse_args()
assert re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', options.image), 'Exact immutable image required'
assert re.fullmatch(r'[0-9a-f]{64}', options.jar_sha256), 'Exact server JAR identity required'
out = options.output_dir.resolve()
out.mkdir(parents=True, exist_ok=False)
repo = Path(__file__).resolve().parents[2]
helper = repo / 'files/puppet-versioned-code.rb'
publisher = repo / 'files/puppet-compiler-snapshot.rb'
store_helper = repo / 'files/puppet-compiler-store.rb'
frozen = out / 'mutable-input/main'
for directory in ['manifests', 'modules/fixture/manifests', 'modules/fixture/files']:
    (frozen / directory).mkdir(parents=True, exist_ok=True)
(frozen / 'manifests/site.pp').write_text('include fixture\n')
(frozen / 'modules/fixture/manifests/init.pp').write_text("class fixture {\n  notify { 'frozen-module-A': }\n}\n")
(frozen / 'modules/fixture/files/probe.txt').write_text('Frozen module static content A.\n')
(frozen / 'environment.conf').write_text('modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo ' + 'a' * 40 + '\n')
setup = r'''require 'fileutils'
require 'digest'
require 'json'
require 'open3'
root = '/fixture'
jar = '/opt/puppetlabs/server/apps/puppetserver/puppet-server-release.jar'
raise 'Wrong server JAR' unless Digest::SHA256.file(jar).hexdigest == ARGV.fetch(0)
File.write('/fixture/id', "#!/bin/sh\nexec ruby /helper/puppet-versioned-code.rb id /release/environments/main /receipt/expected.json \"$@\"\n")
File.write('/fixture/content', "#!/bin/sh\nexec ruby /helper/puppet-compiler-store.rb content /store \"$@\"\n")
File.chmod(0755, '/fixture/id', '/fixture/content')
'''
http = r'''
require 'net/http'
require 'timeout'
FileUtils.mkdir_p('/fixture/conf.d')
FileUtils.mkdir_p('/fixture/conf')
File.write('/fixture/conf/puppet.conf', <<'CONF')
[main]
certname = offline-fixture.nest
codedir = /release
environmentpath = /release/environments
vardir = /fixture/var
logdir = /fixture/log
rundir = /fixture/run
ssldir = /fixture/ssl
cadir = /fixture/ca
settings_catalog = false
[server]
node_terminus = plain
reports = store
environment = main
environment_timeout = 0
CONF
File.write('/fixture/conf.d/server.conf', <<'CONF')
jruby-puppet: {
  ruby-load-path: [ /opt/puppetlabs/puppet/lib/ruby/vendor_ruby ]
  gem-home: /fixture/gems
  master-conf-dir: /fixture/conf
  master-code-dir: /release
  master-var-dir: /fixture/var
  master-log-dir: /fixture/log
  master-run-dir: /fixture/run
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
  rules: [{ match-request: { path: "/", type: path }, allow-unauthenticated: true, sort-order: 1, name: "Offline fixture only" }]
}
versioned-code: { code-id-command: "/fixture/id", code-content-command: "/fixture/content" }
metrics: { server-id: "offline-fixture.nest" }
CONF
config_path = '/fixture/conf.d/server.conf'
load_paths = ['/opt/puppetlabs/puppet/lib/ruby/vendor_ruby', '/opt/puppetlabs/puppet/lib/ruby/gems/3.2.0/gems/concurrent-ruby-1.2.3/lib/concurrent-ruby'] + Dir['/opt/puppetlabs/puppet/lib/ruby/vendor_gems/gems/*/lib']
File.write(config_path, File.read(config_path).sub('ruby-load-path: [ /opt/puppetlabs/puppet/lib/ruby/vendor_ruby ]', 'ruby-load-path: ' + JSON.generate(load_paths)))
bootstrap = File.read('/opt/puppetlabs/server/apps/puppetserver/config/services.d/bootstrap.cfg')
bootstrap += "\npuppetlabs.services.ca.certificate-authority-service/certificate-authority-service\n"
bootstrap += "puppetlabs.trapperkeeper.services.watcher.filesystem-watch-service/filesystem-watch-service\n"
File.write('/fixture/bootstrap.cfg', bootstrap)
log = File.open('/fixture/server.log', 'w')
pid = Process.spawn('java', '-Xmx1500m', '-Djava.io.tmpdir=/fixture', '-cp', jar, 'clojure.main', '-m', 'puppetlabs.trapperkeeper.main', '--config', '/fixture/conf.d', '--bootstrap-config', '/fixture/bootstrap.cfg', out: log, err: log)
begin
  deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + 210
  ready = false
  until ready
    raise 'native server exited during startup' if Process.waitpid(pid, Process::WNOHANG)
    raise 'native server readiness deadline expired' if Process.clock_gettime(Process::CLOCK_MONOTONIC) > deadline
    begin
      r = Net::HTTP.get_response(URI('http://127.0.0.1:8140/status/v1/simple'))
      ready = r.code == '200'
    rescue Errno::ECONNREFUSED, EOFError
    end
    sleep 1 unless ready
  end
  request = {'certname'=>'offline-fixture.nest', 'environment'=>'main', 'facts'=>{'values'=>{'networking'=>{'hostname'=>'offline-fixture', 'fqdn'=>'offline-fixture.nest'}}}, 'trusted_facts'=>{'values'=>{}}, 'persistence'=>{'facts'=>false, 'catalog'=>false}, 'options'=>{'prefer_requested_environment'=>true}}
  uri = URI('http://127.0.0.1:8140/puppet/v4/catalog')
  req = Net::HTTP::Post.new(uri, {'Content-Type'=>'application/json', 'Accept'=>'application/json'})
  req.body = JSON.generate(request)
  response = Net::HTTP.start(uri.host, uri.port, read_timeout: 90) { |h| h.request(req) }
  puts 'HTTP_RESPONSE ' + JSON.generate({'status'=>response.code, 'body'=>response.body})
  raise 'catalog HTTP request failed' unless response.code == '200'
  result = JSON.parse(response.body)
  catalog = result.fetch('catalog')
  expected, status = Open3.capture2('/fixture/id', 'main')
  raise 'wrong code ID' unless status.success? && catalog.fetch('code_id') == expected.strip
  raise 'wrong compiled content' unless catalog.fetch('resources').any? { |r| r['type'] == 'Notify' && r['title'] == 'frozen-module-A' }
  frozen_write_refused = false
  begin
    File.write('/release/environments/main/manifests/site.pp', "notify { 'mutated': }\n")
  rescue Errno::EROFS
    frozen_write_refused = true
  end
  raise 'compiler input mount was writable' unless frozen_write_refused
  FileUtils.mkdir_p('/fixture/mutable-source/main/manifests')
  File.write('/fixture/mutable-source/main/manifests/site.pp', "notify { 'mutable-source-B': }\n")
  v3_uri = URI('http://127.0.0.1:8140/puppet/v3/catalog/offline-fixture.nest?environment=main')
  v3_req = Net::HTTP::Get.new(v3_uri, {'Accept'=>'application/json'})
  v3_response = Net::HTTP.start(v3_uri.host, v3_uri.port, read_timeout: 90) { |h| h.request(v3_req) }
  puts 'V3_RESPONSE ' + JSON.generate({'status'=>v3_response.code, 'body'=>v3_response.body})
  raise 'v3 request failed' unless v3_response.code == '200'
  v3 = JSON.parse(v3_response.body)
  raise 'v3 native identity mismatch' unless v3.fetch('code_id') == expected.strip
  raise 'mutable source leaked into catalog' unless v3.fetch('resources').any? { |r| r['type'] == 'Notify' && r['title'] == 'frozen-module-A' }
  static_uri = URI('http://127.0.0.1:8140/puppet/v3/static_file_content/modules/fixture/files/probe.txt?' + URI.encode_www_form({'environment'=>'main', 'code_id'=>expected.strip}))
  static_response = Net::HTTP.get_response(static_uri)
  puts 'STATIC_RESPONSE ' + JSON.generate({'status'=>static_response.code, 'body'=>static_response.body})
  raise 'static content mismatch' unless static_response.code == '200' && static_response.body == "Frozen module static content A.\n"
  previous = JSON.parse(File.read('/receipt/previous.json'))
  previous_uri = URI('http://127.0.0.1:8140/puppet/v3/static_file_content/modules/fixture/files/probe.txt?' + URI.encode_www_form({'environment'=>'main', 'code_id'=>previous.fetch('code_id')}))
  previous_response = Net::HTTP.get_response(previous_uri)
  raise 'retained identity lost its old static bytes' unless previous_response.code == '200' && previous_response.body == "Retained previous static content.\n"
  wrong_uri = URI('http://127.0.0.1:8140/puppet/v3/static_file_content/modules/fixture/files/probe.txt?' + URI.encode_www_form({'environment'=>'main', 'code_id'=>'sha256:' + '0' * 64}))
  wrong_response = Net::HTTP.get_response(wrong_uri)
  raise 'wrong identity served static content' unless wrong_response.code.to_i >= 400 && wrong_response.body != static_response.body
  unknown_output, unknown_status = Open3.capture2e('/fixture/id', 'other')
  raise 'unknown environment accepted' if unknown_status.success?
  puts 'HTTP_ACCEPTANCE ' + JSON.generate({'code_id'=>catalog['code_id'], 'version'=>catalog['version'], 'catalog'=>catalog, 'native_http_dispatch'=>true, 'v3_catalog'=>v3, 'frozen_write_refused'=>frozen_write_refused, 'mutable_source_ignored'=>true, 'static_content_verified'=>true, 'retained_static_content_verified'=>true, 'previous_code_id'=>previous.fetch('code_id'), 'wrong_identity_status'=>wrong_response.code, 'unknown_environment_refused'=>!unknown_status.success?, 'applied'=>false})
ensure
  Process.kill('TERM', pid) rescue Errno::ESRCH
  begin
    Timeout.timeout(15) { Process.waitpid(pid) }
  rescue Timeout::Error
    Process.kill('KILL', pid) rescue Errno::ESRCH
    Process.waitpid(pid) rescue Errno::ECHILD
  rescue Errno::ECHILD
  end
  log.close
  puts 'SERVER_LOG_BEGIN'
  puts File.read('/fixture/server.log')
  puts 'SERVER_LOG_END'
end
'''
# Open3 is available in the native system Ruby, independently of JRuby.
script = setup + http
(out / 'bootstrap.rb').write_text(script)
image = options.image
receipt_dir = out / 'receipt'
receipt_dir.mkdir(exist_ok=True)
inventory = subprocess.check_output(['ruby', '-r', str(helper), '-e', "puts JSON.generate({'schema'=>1,'environment'=>'main','source'=>'a'*40,'code_id'=>NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(ARGV[0]))})", str(frozen.resolve())], text=True)
(receipt_dir / 'expected.json').write_text(json.dumps(json.loads(inventory), indent=2)+'\n')
store = out / 'store'
store.mkdir(mode=0o700)
static = frozen / 'modules/fixture/files/probe.txt'
static.write_text('Retained previous static content.\n')
previous = subprocess.check_output(['ruby', '-r', str(helper), '-e', "puts JSON.generate({'schema'=>1,'environment'=>'main','source'=>'a'*40,'code_id'=>NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(ARGV[0]))})", str(frozen.resolve())], text=True)
(receipt_dir / 'previous.json').write_text(previous)
for name in ['previous', 'expected']:
    if name == 'expected':
        static.write_text('Frozen module static content A.\n')
    publication = subprocess.run(['ruby', str(store_helper), 'publish', str(frozen.resolve()), str(store.resolve()), str((receipt_dir / (name + '.json')).resolve())], capture_output=True, text=True, check=True)
    (out / ('store-' + name + '.json')).write_text(publication.stdout)
    assert json.loads(publication.stdout)['published'] is True
    assert json.loads(publication.stdout)['compiler_attestation'] is False
(out / 'frozen/environments').mkdir(parents=True, mode=0o755)
# Exercise the actual init copy boundary with independently selected fixture
# identity, then mount only its relocated output in the actual native compiler.
(frozen / 'environment.conf').write_text('config_version = git rev-parse HEAD\n')
publication = subprocess.run(['ruby', str(publisher), str(frozen.resolve()), str((out / 'frozen/environments/main').resolve()), str((receipt_dir / 'expected.json').resolve())], capture_output=True, text=True, check=True)
(out / 'publication.json').write_text(publication.stdout)
assert json.loads(publication.stdout)['code_id'] == json.loads(inventory)['code_id']
(frozen / 'modules/fixture/manifests/init.pp').write_text("class fixture { notify { 'changed-original-input': } }\n")
args = ['podman', 'run', '-i', '--rm', '--pull=never', '--network=none', '--read-only', '--read-only-tmpfs=false', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--memory=3g', '--pids-limit=512', '--tmpfs', '/fixture:rw,nosuid,size=256m', '--mount', 'type=bind,src=' + str((out / 'frozen').resolve()) + ',dst=/release,ro', '--mount', 'type=bind,src=' + str(receipt_dir.resolve()) + ',dst=/receipt,ro', '--mount', 'type=bind,src=' + str(helper) + ',dst=/helper/puppet-versioned-code.rb,ro', '--entrypoint', 'ruby', image, '-', options.jar_sha256]
args[args.index('--entrypoint'):args.index('--entrypoint')] = [
    '--mount', 'type=bind,src=' + str(store.resolve()) + ',dst=/store,ro',
    '--mount', 'type=bind,src=' + str(publisher) + ',dst=/helper/puppet-compiler-snapshot.rb,ro',
    '--mount', 'type=bind,src=' + str(store_helper) + ',dst=/helper/puppet-compiler-store.rb,ro',
]
r = subprocess.run(args, input=script, capture_output=True, text=True, timeout=360)
(out / 'stdout').write_text(r.stdout)
(out / 'stderr').write_text(r.stderr)
(out / 'invocation.json').write_text(json.dumps({'argv':args, 'exit_code':r.returncode}, indent=2)+'\n')
print('exit_code:', r.returncode)
print(r.stdout[-15000:])
print(r.stderr[-5000:])
if r.returncode:
    raise SystemExit(r.returncode)
rows = [json.loads(line[len('HTTP_ACCEPTANCE '):]) for line in r.stdout.splitlines() if line.startswith('HTTP_ACCEPTANCE ')]
assert len(rows) == 1
(out / 'acceptance.json').write_text(json.dumps(rows[0], indent=2)+'\n')
print('Actual native HTTP catalog acceptance retained; no host agent or production service was used.')
