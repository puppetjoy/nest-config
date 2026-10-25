"""Exercise the exact rendered init and paired wrappers with private disposable output."""
import argparse
import re
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
import yaml

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manifest',type=Path,required=True)
parser.add_argument('--server-image',required=True)
parser.add_argument('--jar-sha256',required=True)
parser.add_argument('--output-dir',type=Path,required=True)
parser.add_argument('--http',action='store_true',help='Also start the offline native JAR and verify retained and legacy HTTP routes')
args=parser.parse_args()
assert re.fullmatch(r'ghcr.io/openvoxproject/openvoxserver@sha256:[0-9a-f]{64}',args.server_image)
assert re.fullmatch(r'[0-9a-f]{64}',args.jar_sha256)
OUT=args.output_dir.resolve()
OUT.mkdir(exist_ok=False,parents=True)
items=list(yaml.safe_load_all(args.manifest.read_bytes()))
dep=next(x for x in items if x.get('kind')=='Deployment' and x['metadata']['name']=='puppet-puppetserver')
pod=dep['spec']['template']['spec']
inits=[c for c in pod['initContainers'] if c['name'].startswith('compiler-snapshot-')]
assert inits and all(re.fullmatch(r'registry.eyrie/nest/config/main@sha256:[0-9a-f]{64}',c['image']) for c in inits)
assert not any(m['name']=='compiler-snapshots' for c in pod['containers'][1:] for m in c.get('volumeMounts',[]))
assert not any(m['name']=='puppet-code-storage' for m in pod['containers'][0]['volumeMounts'])
expected=json.loads(inits[-1]['command'][3])
server=args.server_image
jar_sha256=args.jar_sha256
volume='compiler-2045-'+uuid.uuid4().hex
common=['podman','run','--rm','--pull=never','--network=none','--read-only','--read-only-tmpfs=false',
        '--security-opt=no-new-privileges','--memory=2g','--pids-limit=512','--cpus=2']

def run(name,args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=600)
    for suffix,data in [('stdout',result.stdout),('stderr',result.stderr)]:
        (OUT/(name+'.'+suffix)).write_text(data)
    assert result.returncode==0, name+' failed; inspect original retained output'
    return result.stdout

subprocess.run(['podman','volume','create',volume],check=True,capture_output=True)
try:
    for index,init in enumerate(inits):
        command=common+['--user=0:0','--cap-drop=ALL','--cap-add=CHOWN','--cap-add=DAC_OVERRIDE','--cap-add=FOWNER',
                        '--volume',volume+':/compiler','--entrypoint',init['command'][0],init['image'],*init['command'][1:]]
        output=run('init-'+str(index),command)
        if index==len(inits)-1:
            result=json.loads(output)
            assert result['code_id']==expected['code_id'] and result['compiler_attestation'] is False
    probe='''require 'json'; require 'digest'; require 'open3'; require 'fileutils'
expected=JSON.parse(ARGV.fetch(0))
raise unless Digest::SHA256.file('/opt/puppetlabs/server/apps/puppetserver/puppet-server-release.jar').hexdigest==ARGV.fetch(2)
base='/compiler/store/'+expected.fetch('code_id').delete_prefix('sha256:')
raise unless File.stat('/compiler/store').uid==999 && File.stat(base+'/expected.json').uid==999
FileUtils.mkdir_p('/etc/puppetlabs/puppetserver/conf.d')
2.times do
 output,status=Open3.capture2e('/docker-entrypoint.d/30-set-permissions.sh')
 raise output unless status.success?
 output,status=Open3.capture2e('/compiler/runtime/entrypoint')
 raise output unless status.success?
 raise unless File.symlink?('/etc/puppetlabs/puppetserver/conf.d/versioned-code.conf')
 raise unless File.realpath('/etc/puppetlabs/puppetserver/conf.d/versioned-code.conf')=='/compiler/runtime/versioned-code.conf'
end
Process::GID.change_privilege(999)
Process::UID.change_privilege(999)
settings,status=Open3.capture2e('puppet','config','print','environmentpath','basemodulepath','--section','server','--confdir','/etc/puppetlabs/puppet')
raise settings unless status.success? && settings.include?('environmentpath = '+base) && settings.include?('basemodulepath = /compiler/empty-modules')
identity,status=Open3.capture2e('/compiler/runtime/id','main')
raise identity unless status.success? && identity.strip==expected.fetch('code_id')
content,status=Open3.capture2('/compiler/runtime/content','main',expected.fetch('code_id'),'.modules/nest/files/puppet-versioned-code.rb')
raise unless status.success? && Digest::SHA256.hexdigest(content)==ARGV.fetch(1)
_wrong,_stderr,status=Open3.capture3('/compiler/runtime/content','main','sha256:'+('0'*64),'.modules/nest/files/puppet-versioned-code.rb')
raise if status.success?
['/compiler/store/write-probe','/etc/puppetlabs/puppetserver/conf.d/versioned-code.conf'].each do |path|
 begin
  File.write(path,'no')
  raise 'Snapshot or linked hook configuration writable'
 rescue Errno::EROFS
 end
end
puts JSON.generate('source'=>expected.fetch('source'),'code_id'=>identity.strip,'uid'=>Process.euid,'paired_wrappers'=>true,'read_only_refusal'=>true,'isolated_module_paths'=>true,'native_permissions_and_hook_repeat'=>true,'static_content_digest_verified'=>true,'wrong_static_id_refused'=>true,'native_jar_catalog_requested'=>false,'compiler_attestation'=>false)
'''
    server_args=common+['--user=0:0','--cap-drop=ALL','--cap-add=SETUID','--cap-add=SETGID','--cap-add=CHOWN','--cap-add=DAC_OVERRIDE','--tmpfs','/etc/puppetlabs/puppet:rw,mode=777,size=16m',
                 '--tmpfs','/etc/puppetlabs/puppetserver:rw,mode=755,size=16m',
                 '--tmpfs','/opt/puppetlabs/server/data/puppetserver:rw,mode=755,size=16m,notmpcopyup',
                 '--tmpfs','/var/log/puppetlabs/puppetserver:rw,mode=755,size=16m',
                 '--tmpfs','/work:rw,mode=777,size=32m','--env','HOME=/work','--env','TMPDIR=/work',
                 '--volume',volume+':/compiler:ro','--entrypoint','ruby',server,'-e',probe,json.dumps(expected),
                 hashlib.sha256((ROOT/'files/puppet-versioned-code.rb').read_bytes()).hexdigest(),jar_sha256]
    report=json.loads(run('server',server_args))
    assert report['code_id']==expected['code_id'] and report['uid']==999
    report.update(image=inits[-1]['image'],retained_releases=len(inits)-1,server_image=server,jar_sha256=jar_sha256,source_overlay=False,network=False,host_mounts=False,
                  production_hooks_enabled=False,program_complete=False)
    if args.http:
        receipts=[json.loads(init['command'][3]) for init in inits]
        http_args=common+['--memory=3g','--user=0:0','--cap-drop=ALL','--cap-add=SETUID','--cap-add=SETGID','--cap-add=CHOWN','--cap-add=DAC_OVERRIDE',
                          '--tmpfs','/etc/puppetlabs/puppet:rw,mode=777,size=16m',
                          '--tmpfs','/etc/puppetlabs/puppetserver/conf.d:rw,mode=755,size=16m',
                          '--tmpfs','/work:rw,mode=777,size=256m','--env','HOME=/work','--env','TMPDIR=/work',
                          '--volume',volume+':/compiler:ro',
                          '--volume',str(ROOT/'spec/files/openvox_compiler_http_native.rb')+':/probe.rb:ro',
                          '--entrypoint','ruby',server,'/probe.rb',json.dumps(expected),json.dumps(receipts),jar_sha256]
        http_report=json.loads(run('native-http',http_args))
        assert http_report['uid']==999 and http_report['native_http_dispatch'] is True
        assert [row['code_id'] for row in http_report['static_content']]==[receipt['code_id'] for receipt in receipts]
        report['native_http']=http_report
        report['native_jar_catalog_requested']=True
        report['host_mounts']=True
        report['host_data_mounts']=False
        report['test_script_bind_only']=True
    (OUT/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    assert json.loads((OUT/'acceptance.json').read_bytes())==report
    print(json.dumps(report))
finally:
    subprocess.run(['podman','volume','rm',volume],check=True,capture_output=True)
