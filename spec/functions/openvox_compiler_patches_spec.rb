require 'spec_helper'
require 'json'
require 'open3'
require 'tmpdir'
require 'fileutils'
require_relative '../../files/puppet-compiler-store'

describe 'nest::openvox_compiler_patches' do
  let(:revision) { 'a' * 40 }
  let(:receipt) { { 'schema' => 1, 'environment' => 'main', 'source' => revision, 'code_id' => 'sha256:' + ('b' * 64) } }
  let(:member) { { 'image' => 'registry.eyrie/nest/config/main@sha256:' + ('c' * 64), 'expected' => receipt } }
  let(:selection) { { 'schema' => 1, 'current' => member, 'retained' => [] } }

  def rendered(value = selection)
    subject.execute(value, 'puppet').first.fetch('patch')
  end

  def inits(value = selection)
    rendered(value).select { |op| op['path'] == '/spec/template/spec/initContainers/-' }.map { |op| op.fetch('value') }
  end

  it { is_expected.to run.with_params(nil, 'puppet').and_return([]) }

  it 'uses an independently selected digest and pod-private init-only writable storage' do
    init = inits.first
    expect(init['image']).to eq(member['image'])
    expect(init['securityContext']).to include('readOnlyRootFilesystem' => true, 'allowPrivilegeEscalation' => false)
    expect(init['volumeMounts']).to eq([{ 'name' => 'compiler-snapshots', 'mountPath' => '/compiler' }])
    mounts = rendered.select { |op| op['path'] == '/spec/template/spec/containers/0/volumeMounts/-' }.map { |op| op['value'] }
    expect(mounts).to all(include('readOnly' => true))
    expect(mounts.map { |mount| mount['mountPath'] }).to include('/compiler', '/docker-custom-entrypoint.d/20-compiler.sh', '/etc/puppetlabs/puppetserver/conf.d/versioned-code.conf')
  end

  it 'removes only the proven mutable compiler code mount and refuses chart layout drift' do
    expected = [
      { 'op' => 'test', 'path' => '/spec/template/spec/containers/0/name', 'value' => 'puppet-puppetserver' },
      { 'op' => 'test', 'path' => '/spec/template/spec/containers/0/volumeMounts/6/name', 'value' => 'puppet-code-storage' },
      { 'op' => 'test', 'path' => '/spec/template/spec/containers/0/volumeMounts/6/mountPath', 'value' => '/etc/puppetlabs/code/' },
      { 'op' => 'remove', 'path' => '/spec/template/spec/containers/0/volumeMounts/6' },
    ]
    expect(rendered.take(4)).to eq(expected)
    expect(rendered.none? { |op| op['path'].include?('/containers/1/') }).to be(true)
  end

  it 'copies retained releases first and seals only after the current release' do
    prior = Marshal.load(Marshal.dump(member))
    prior['expected']['code_id'] = 'sha256:' + ('d' * 64)
    prior['expected']['source'] = 'e' * 40
    values = inits(selection.merge('retained' => [prior]))
    expect(values.length).to eq(2)
    expect(JSON.parse(values.first['command'][3])).to eq(prior['expected'])
    expect(values.first['command'][2]).not_to include('FileUtils.chown_R')
    expect(values.last['command'][2]).to include('FileUtils.chown_R', 'code-id-command:', 'code-content-command:')
    expect(JSON.parse(values.last['command'][5])).to eq([prior['expected'], receipt])
  end

  it 'rejects mutable images, malformed receipts, duplicate identities and unknown fields' do
    invalid = [
      selection.merge('current' => member.merge('image' => 'registry.eyrie/nest/config/main:latest')),
      selection.merge('current' => member.merge('expected' => receipt.merge('schema' => true))),
      selection.merge('current' => member.merge('expected' => receipt.merge('source' => 'main'))),
      selection.merge('current' => member.merge('expected' => receipt.merge('code_id' => 'sha256:bad'))),
      selection.merge('current' => member.merge('expected' => receipt.merge('environment' => 'test'))),
      selection.merge('retained' => [member]), selection.merge('extra' => true)
    ]
    invalid.each { |value| expect { rendered(value) }.to raise_error(ArgumentError) }
  end

  context 'with real inert publication inputs' do
    let(:work) { Dir.mktmpdir('compiler-pod-', ENV.fetch('TMPDIR', nil)) }
    let(:input) { File.join(work, 'input') }
    let(:volume) { File.join(work, 'volume') }
    let(:fixture_files) { File.join(work, 'files') }
    let(:receipt) do
      { 'schema' => 1, 'environment' => 'main', 'source' => revision,
        'code_id' => NestPuppetVersionedCode.code_id(NestPuppetVersionedCode.inventory(File.join(input, 'main'))) }
    end

    before(:each) do
      FileUtils.mkdir_p(File.join(input, 'main/modules/fixture/files'))
      File.write(File.join(input, 'main/modules/fixture/files/probe'), "frozen\n")
      File.write(File.join(input, 'main/environment.conf'), "modulepath = modules:.modules\nmanifest = manifests\nconfig_version = /bin/echo #{revision}\n")
      File.write(File.join(input, 'expected.json'), JSON.generate(receipt))
      FileUtils.mkdir_p(fixture_files)
      ['puppet-versioned-code.rb', 'puppet-compiler-snapshot.rb', 'puppet-compiler-store.rb'].each do |name|
        FileUtils.cp(File.expand_path("../../files/#{name}", __dir__), fixture_files)
      end
      Dir.mkdir(volume, 0o700)
    end

    after(:each) { FileUtils.remove_entry(work) }

    def execute_init
      command = inits.first.fetch('command').dup
      # Host test uses only inert temp input; native container acceptance checks
      # the actual read-only mount and UID transition separately.
      command[2] = command[2].gsub('/compiler', volume).gsub('/opt/nest/files', fixture_files).gsub('/opt/nest-compiler-release', input)
      command[2] = command[2].sub("NestPuppetVersionedCode.read_only?('#{input}/main')", 'true')
      command[2] = command[2].sub("FileUtils.chown_R(999, 999, '#{volume}')", 'nil')
      Open3.capture3(*command)
    end

    it 'executes the generated copy and paired hook setup, with no mutable input links' do
      stdout, stderr, status = execute_init
      expect(status.success?).to be(true), stderr
      expect(JSON.parse(stdout)).to include('code_id' => receipt['code_id'], 'compiler_attestation' => false)
      root = File.join(volume, 'store', receipt['code_id'].delete_prefix('sha256:'), 'main')
      expect(File.read(File.join(root, 'modules/fixture/files/probe'))).to eq("frozen\n")
      File.write(File.join(input, 'main/modules/fixture/files/probe'), 'changed input')
      expect(File.read(File.join(root, 'modules/fixture/files/probe'))).to eq("frozen\n")
      expect(File.read(File.join(volume, 'runtime/entrypoint'))).to include('environmentpath', 'basemodulepath', '/empty-modules')
      expect(File.read(File.join(volume, 'runtime/versioned-code.conf'))).to include('code-id-command:', 'code-content-command:')
      expect(File.read(File.join(volume, 'runtime/content'))).to include('puppet-compiler-store.rb content')
      _stdout, _stderr, repeat = execute_init
      expect(repeat.success?).to be(false)
      expect(File.read(File.join(root, 'modules/fixture/files/probe'))).to eq("frozen\n")
    end

    it 'refuses a wrong expected release before publication or hook setup' do
      File.write(File.join(input, 'expected.json'), JSON.generate(receipt.merge('source' => 'f' * 40)))
      _stdout, _stderr, status = execute_init
      expect(status.success?).to be(false)
      expect(Dir.children(volume)).to eq([])
    end

    it 'preserves failed partial publication and prevents compiler setup' do
      File.write(File.join(input, 'main/modules/fixture/files/probe'), 'wrong bytes')
      _stdout, _stderr, status = execute_init
      expect(status.success?).to be(false)
      expect(Dir.children(File.join(volume, 'store'))).to include(receipt['code_id'].delete_prefix('sha256:') + '.pending')
      expect(File).not_to exist(File.join(volume, 'runtime'))
    end
  end
end
