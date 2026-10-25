# frozen_string_literal: true

require 'json'

# KubeCM's existing ordered patch interface; absent selection changes nothing.
Puppet::Functions.create_function(:'nest::openvox_compiler_patches') do
  dispatch :patches do
    param 'Optional[Hash]', :selection
    param 'String', :service
    return_type 'Array[Hash]'
  end

  def check(value)
    raise ArgumentError, 'Invalid immutable OpenVox compiler selection' unless value
  end

  def member(value)
    check(value.is_a?(Hash) && value.keys.sort == ['expected', 'image'])
    check(value['image'].is_a?(String) && %r{\Aregistry\.eyrie/nest/config/main@sha256:[0-9a-f]{64}\z}.match?(value['image']))
    receipt = value['expected']
    check(receipt.is_a?(Hash) && receipt.keys.sort == ['code_id', 'environment', 'schema', 'source'])
    check(receipt['schema'].instance_of?(Integer) && receipt['schema'] == 1 && receipt['environment'] == 'main')
    check(receipt['source'].is_a?(String) && %r{\A[0-9a-f]{40}\z}.match?(receipt['source']))
    check(receipt['code_id'].is_a?(String) && %r{\Asha256:[0-9a-f]{64}\z}.match?(receipt['code_id']))
    value
  end

  def operation(op, path, value)
    { 'op' => op, 'path' => path, 'value' => value }
  end

  def patches(selection, service)
    return [] if selection.nil?

    check(%r{\A[a-z][a-z0-9-]*\z}.match?(service))
    check(selection.keys.sort == ['current', 'retained', 'schema'])
    check(selection['schema'].instance_of?(Integer) && selection['schema'] == 1 && selection['retained'].is_a?(Array))
    current = member(selection['current'])
    releases = selection['retained'].map { |value| member(value) } + [current]
    identities = releases.map { |value| value['expected']['code_id'] }
    check(identities.uniq == identities)
    prefix = '/spec/template/spec'
    # Tests deliberately bind the pinned chart's layout. Fail rendering rather
    # than removing an unrelated mount after an upstream chart/layout change.
    result = [
      operation('test', "#{prefix}/containers/0/name", "#{service}-puppetserver"),
      operation('test', "#{prefix}/containers/0/volumeMounts/6/name", 'puppet-code-storage'),
      operation('test', "#{prefix}/containers/0/volumeMounts/6/mountPath", '/etc/puppetlabs/code/'),
      { 'op' => 'remove', 'path' => "#{prefix}/containers/0/volumeMounts/6" },
      operation('add', "#{prefix}/volumes/-", { 'name' => 'compiler-snapshots', 'emptyDir' => {} }),
      operation('add', "#{prefix}/containers/0/volumeMounts/-", { 'name' => 'compiler-snapshots', 'mountPath' => '/compiler', 'readOnly' => true }),
      operation('add', '/spec/template/metadata/annotations/nest.eyrie~1compiler-selection', JSON.generate(selection)),
    ]
    # The old r10k sidecar keeps its normal mutable tree, but cannot see this
    # volume. Only init containers write it; none survive compiler startup.
    releases.each_with_index do |release, index|
      script = <<~'RUBY'
        require '/opt/nest/files/puppet-compiler-store'
        require 'fileutils'
        expected = JSON.parse(ARGV.fetch(0))
        supplied = NestPuppetCompilerStore.read_receipt('/opt/nest-compiler-release/expected.json')
        NestPuppetVersionedCode.check(supplied == expected)
        NestPuppetVersionedCode.check(NestPuppetVersionedCode.read_only?('/opt/nest-compiler-release/main'))
        Dir.mkdir('/compiler/store', 0700) if ARGV.fetch(1) == 'first'
        NestPuppetCompilerStore.publish('/opt/nest-compiler-release/main', '/compiler/store', expected)
      RUBY
      args = [JSON.generate(release['expected']), (index == 0) ? 'first' : 'next']
      if index == releases.length - 1
        script += seal_script
        args += [JSON.generate(releases.map { |value| value['expected'] }), current['expected']['code_id']]
      end
      init = {
        'name' => "compiler-snapshot-#{index}", 'image' => release['image'], 'imagePullPolicy' => 'IfNotPresent',
        'command' => ['ruby', '-e', script, *args],
        'securityContext' => { 'runAsUser' => 0, 'runAsGroup' => 0, 'readOnlyRootFilesystem' => true,
                               'allowPrivilegeEscalation' => false, 'capabilities' => { 'drop' => ['ALL'], 'add' => ['CHOWN', 'DAC_OVERRIDE', 'FOWNER'] } },
        'volumeMounts' => [{ 'name' => 'compiler-snapshots', 'mountPath' => '/compiler' }],
      }
      result << operation('add', "#{prefix}/initContainers/-", init)
    end
    result += [
      operation('add', "#{prefix}/containers/0/volumeMounts/-", { 'name' => 'compiler-snapshots', 'mountPath' => '/docker-custom-entrypoint.d/20-compiler.sh',
                                                               'subPath' => 'runtime/entrypoint', 'readOnly' => true }),
      operation('add', "#{prefix}/containers/0/volumeMounts/-", { 'name' => 'compiler-snapshots', 'mountPath' => '/etc/puppetlabs/puppetserver/conf.d/versioned-code.conf',
                                                               'subPath' => 'runtime/versioned-code.conf', 'readOnly' => true }),
    ]
    [{ 'target' => { 'group' => 'apps', 'version' => 'v1', 'kind' => 'Deployment', 'name' => "#{service}-puppetserver" }, 'patch' => result }]
  end

  def seal_script
    <<~'RUBY'
      receipts = JSON.parse(ARGV.fetch(2))
      current = ARGV.fetch(3)
      wanted = receipts.map { |receipt| receipt.fetch('code_id').delete_prefix('sha256:') }.sort
      NestPuppetVersionedCode.check(Dir.children('/compiler/store').sort == (wanted + ['.publish.lock']).sort)
      receipts.each do |receipt|
        path = NestPuppetCompilerStore.release_path('/compiler/store', receipt.fetch('code_id'))
        NestPuppetVersionedCode.check(NestPuppetCompilerStore.read_receipt(File.join(path, 'expected.json')) == receipt)
        NestPuppetCompilerStore.snapshot('/compiler/store', receipt.fetch('code_id'), readonly: ->(_path) { true })
      end
      Dir.mkdir('/compiler/runtime', 0755)
      Dir.mkdir('/compiler/empty-modules', 0755)
      ['puppet-versioned-code.rb', 'puppet-compiler-snapshot.rb', 'puppet-compiler-store.rb'].each do |name|
        FileUtils.copy_file(File.join('/opt/nest/files', name), File.join('/compiler/runtime', name))
        File.chmod(0644, File.join('/compiler/runtime', name))
      end
      root = NestPuppetCompilerStore.release_path('/compiler/store', current)
      wrappers = {
        'id' => "#!/bin/sh\nexec /opt/puppetlabs/puppet/bin/ruby /compiler/runtime/puppet-versioned-code.rb id #{root}/main #{root}/expected.json \"$@\"\n",
        'content' => "#!/bin/sh\nexec /opt/puppetlabs/puppet/bin/ruby /compiler/runtime/puppet-compiler-store.rb content /compiler/store \"$@\"\n",
        'entrypoint' => "#!/bin/sh\nset -eu\npuppet config set --confdir /etc/puppetlabs/puppet --section server environmentpath #{root}\npuppet config set --confdir /etc/puppetlabs/puppet --section server basemodulepath /compiler/empty-modules\npuppet config set --confdir /etc/puppetlabs/puppet --section server environment main\n",
      }
      wrappers.each do |name, content|
        File.open(File.join('/compiler/runtime', name), File::WRONLY | File::CREAT | File::EXCL, 0755) { |file| file.write(content) }
      end
      File.open('/compiler/runtime/versioned-code.conf', File::WRONLY | File::CREAT | File::EXCL, 0644) do |file|
        file.write("versioned-code: { code-id-command: /compiler/runtime/id, code-content-command: /compiler/runtime/content }\n")
      end
      # UID/GID are the pinned chart's Puppet service identity. Ownership changes
      # do not alter the inventoried modes/content. All later mounts are read-only.
      FileUtils.chown_R(999, 999, '/compiler')
      puts JSON.generate('kind' => 'nest_openvox_compiler_init', 'code_id' => current, 'retained' => receipts.length - 1, 'compiler_attestation' => false)
    RUBY
  end
end
