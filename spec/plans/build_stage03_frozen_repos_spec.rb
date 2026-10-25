require 'spec_helper'
require 'bolt_spec/plans'
require 'tmpdir'

RSpec.describe 'Stage 0 and Stage 3 frozen repository inputs' do
  include BoltSpec::Plans

  let(:plan_modulepath) { Dir.mktmpdir('nest-stage03-frozen-spec-') }
  let(:pins) { { 'gentoo' => 'a' * 40, 'nest' => 'b' * 40, 'haskell' => 'c' * 40 } }
  let(:base) { "registry.example/nest/base@sha256:#{'d' * 64}" }
  let(:catalog) { { 'source' => 'e' * 40, 'base' => "registry.example/nest/bolt@sha256:#{'f' * 64}" } }
  let(:ca_sha256) { 'a' * 64 }
  let(:identity_reference) { '12345678-1234-4123-8123-123456789abc' }
  let(:inventory_data) do
    { 'targets' => [{ 'name' => 'falcon', 'uri' => 'falcon.nest',
                     'config' => { 'transport' => 'ssh', 'ssh' => { 'user' => 'joy' } } }] }
  end
  let(:catalog_check) do
    "python3 /opt/nest/scripts/nest-executor-inputs.py check --source #{catalog['source']} --base #{catalog['base']} > /dev/null"
  end
  let(:publication) do
    { 'release' => 'fixture-release', 'expectations' => "sha256:#{'a' * 64}",
      'staging' => '/private/staging', 'staging_guid' => '123', 'receipts' => '/private/receipts', 'parent_guid' => '456' }
  end
  let(:publication_options) do
    options(3).merge('catalog_inputs' => catalog, 'identityroot' => '/private/fixture-host',
                     'hostroot' => '/nest/releases/fixture-release/hosts/fixture-host', 'root_publication' => publication)
  end
  let(:finish_command) do
    "python3 /opt/nest/files/build/finish-stage3-root.py fixture /private/staging 123 /private/receipts fixture-host fixture-release 456 sha256:#{'a' * 64} /private/fixture-host"
  end
  let(:root_artifact) do
    { 'root' => { 'path' => publication_options['hostroot'], 'dataset_guid' => '789', 'content_digest' => "sha256:#{'b' * 64}" } }
  end

  def modulepath
    [plan_modulepath, File.expand_path('../fixtures/modules', __dir__)]
  end

  around :each do |example|
    File.symlink(File.expand_path('../..', __dir__), File.join(plan_modulepath, 'nest'))
    example.run
  ensure
    FileUtils.remove_entry(plan_modulepath)
  end

  before :each do
    # BoltSpec indexes command stubs by exact string; regex exclusions need
    # RSpec expectations while all other calls retain the real mock behavior.
    allow(executor).to receive(:run_command).and_call_original
  end

  def options(stage)
    common = { 'container' => 'fixture', 'build' => true, 'deploy' => false, 'qemu_user_targets' => [], 'repo_revisions' => pins }
    if stage.zero?
      common.merge('cpu' => 'arm1176', 'from_image' => base, 'registry' => 'localhost')
    else
      common.merge('hostname' => 'fixture-host', 'platform' => 'vanilla', 'variant' => 'server', 'stage2_image' => base,
                   'identity_ca_sha256' => ca_sha256, 'identity_reference' => identity_reference)
    end
  end

  def mocks(stage)
    allow_any_command
    allow_apply_prep
    allow_apply
    expect_command('eix-sync -aq').not_be_called
    expect_command('emerge --sync').not_be_called
    expect_command('podman volume rm -f fixture-frozen-repos')
    expect_script('nest/build/stage0-runtime.rb').be_called_times(3) if stage.zero?
  end

  [0, 3].each do |stage|
    it "rejects incomplete or malformed Stage #{stage} pins before any command" do
      expect_command('podman rm -f fixture').not_be_called
      expect_command('podman volume rm -f fixture-debug').not_be_called
      expect_command('podman volume rm -f fixture-frozen-repos').not_be_called
      [{}, pins.reject { |key, _| key == 'haskell' }, pins.merge('extra' => 'e' * 40),
       pins.merge('nest' => 'main'), pins.merge('gentoo' => "#{'a' * 40}\n")].each do |bad|
        expect(run_plan("nest::build::stage#{stage}", options(stage).merge('repo_revisions' => bad)).ok?).to be(false)
      end
    end

    it "rejects existing or unbuilt Stage #{stage} containers and mutable bases before mutation" do
      expect_command('podman rm -f fixture').not_be_called
      expect_command('podman volume rm -f fixture-debug').not_be_called
      expect_command('podman volume rm -f fixture-frozen-repos').not_be_called
      key = stage.zero? ? 'from_image' : 'stage2_image'
      [{ 'init' => false }, { 'build' => false }, { key => nil }, { key => 'registry.example/nest/base:latest' }].each do |override|
        expect(run_plan("nest::build::stage#{stage}", options(stage).merge(override)).ok?).to be(false)
      end
    end

    it "prepares complete Stage #{stage} repositories and checks after configuration and before output" do
      mocks(stage)
      prefix = if stage.zero?
                 'podman create --dns=172.22.4.3 --env=LANG --init --name=fixture --pull=always --volume=/nest:/nest --volume=fixture-debug:/usr/lib/debug '
               else
                 'podman create --init --hostname=fixture-host --name=fixture --no-hosts --pull=always --volume=/falcon:/falcon --volume=/nest:/nest '
               end
      spaces = stage.zero? ? '  ' : '   '
      expect_command("#{prefix}--volume=fixture-frozen-repos:/var/db/repos:nocopy#{spaces}#{base} sleep infinity\n")
      expect_script('nest/build/freeze-repos.py').with_params('arguments' => ['prepare', *pins.values])
      expect_script('nest/build/freeze-repos.py').with_params('arguments' => ['check', *pins.values]).be_called_times(2)
      expect(run_plan("nest::build::stage#{stage}", options(stage)).ok?).to be(true)
    end

    it "stops Stage #{stage} before configuration or packages after preparation failure" do
      allow_any_command
      expect_command('podman volume rm -f fixture-frozen-repos')
      expect_script('nest/build/freeze-repos.py').with_params('arguments' => ['prepare', *pins.values]).error_with('msg' => 'Missing commit', 'kind' => 'fixture/fetch')
      expect(executor).not_to receive(:run_command).with(anything, %r{emerge }, anything, anything)
      expect(executor).not_to receive(:run_command).with(anything, %r{eselect profile}, anything, anything)
      expect(run_plan("nest::build::stage#{stage}", options(stage)).ok?).to be(false)
    end

    it "stops Stage #{stage} before package build or publication when a catalog drifts repositories" do
      allow_any_command
      allow_apply_prep
      allow_apply
      expect_script('nest/build/stage0-runtime.rb') if stage.zero?
      expect_script('nest/build/freeze-repos.py').with_params('arguments' => ['prepare', *pins.values])
      expect_script('nest/build/freeze-repos.py').with_params('arguments' => ['check', *pins.values]).error_with('msg' => 'Changed HEAD', 'kind' => 'fixture/drift')
      expect(executor).not_to receive(:run_command).with(anything, %r{emerge --deep}, anything, anything)
      expect(executor).not_to receive(:run_command).with(anything, %r{podman commit}, anything, anything)
      expect(executor).not_to receive(:run_command).with(anything, %r{zsh -c .*rsync}, anything, anything)
      expect(run_plan("nest::build::stage#{stage}", options(stage).merge('deploy' => true)).ok?).to be(false)
    end

    it "preserves the legacy Stage #{stage} sync and volume behavior without repository pins" do
      allow_any_command
      allow_apply_prep
      allow_apply
      expect_script('nest/build/stage0-runtime.rb').be_called_times(3) if stage.zero?
      expect_script('nest/build/freeze-repos.py').not_be_called
      expect_command('eix-sync -aq')
      expect_command('podman volume rm -f fixture-frozen-repos').not_be_called
      expect(run_plan("nest::build::stage#{stage}", options(stage).merge('repo_revisions' => nil)).ok?).to be(true)
    end
  end

  it 'refuses frozen raw Gentoo bootstrap instead of silently syncing or installing Git from floating inputs' do
    expect_command('podman rm -f fixture').not_be_called
    expect_command('podman volume rm -f fixture-debug').not_be_called
    expect_command('podman volume rm -f fixture-frozen-repos').not_be_called
    gentoo = "registry.example/gentoo/stage3@sha256:#{'e' * 64}"
    expect(run_plan('nest::build::stage0', options(0).merge('from_image' => gentoo)).ok?).to be(false)
  end

  it 'verifies the installed executor before initialization and around the local Stage 3 catalog' do
    mocks(3)
    allow(executor).to receive(:run_command).and_call_original
    expect(executor).not_to receive(:run_command).with(anything, %r{puppet.*agent}, anything, anything)
    expect_script('nest/build/freeze-repos.py').be_called_times(3)
    args = ['/private/fixture-host', '/nest/hosts/fixture-host', 'fixture-host', ca_sha256, '--identity-reference', identity_reference]
    expect_script('nest/build/check-stage3-paths.py').with_params('arguments' => args).be_called_times(3)
    expect_script('nest/build/check-stage3-paths.py')
      .with_params('arguments' => args + ['--install']).with_targets('fixture-host')
    expect_command(catalog_check).with_targets('localhost').be_called_times(3)
    expect(run_plan('nest::build::stage3', options(3).merge('catalog_inputs' => catalog, 'identityroot' => '/private/fixture-host')).ok?).to be(true)
  end

  it 'refuses incomplete catalog inputs and conflicting legacy modes before any command' do
    expect(executor).not_to receive(:run_command)
    [{ 'catalog_inputs' => {} }, { 'catalog_inputs' => catalog.merge('source' => 'main') },
     { 'catalog_inputs' => catalog.merge('base' => 'registry.example/nest/bolt:latest') },
     { 'catalog_inputs' => catalog.merge('extra' => true) }, { 'repo_revisions' => nil },
     { 'stage2_image' => nil }, { 'init' => false }, { 'build' => false },
     { 'puppet_environment' => 'main' }, { 'puppet_environment' => '' },
     { 'identity_ca_sha256' => nil }, { 'identity_ca_sha256' => 'mutable' }, { 'identity_ca_sha256' => "#{ca_sha256}\n" },
     { 'identity_reference' => nil }, { 'identity_reference' => 'latest' }, { 'identity_reference' => "#{identity_reference}\n" }].each do |override|
      params = options(3).merge('catalog_inputs' => catalog).merge(override)
      expect(run_plan('nest::build::stage3', params).ok?).to be(false)
    end
  end

  it 'stops before removing any container or repository when the installed catalog inputs drift' do
    expect_command(catalog_check).error_with('msg' => 'Executor inventory changed', 'kind' => 'fixture/drift')
    expect_command('podman rm -f fixture').not_be_called
    expect_command('podman volume rm -f fixture-frozen-repos').not_be_called
    expect(executor).not_to receive(:run_command).with(anything, %r{emerge }, anything, anything)
    expect(executor).not_to receive(:run_command).with(anything, %r{zsh -c .*rsync}, anything, anything)
    params = options(3).merge('catalog_inputs' => catalog)
    expect(run_plan('nest::build::stage3', params).ok?).to be(false)
  end

  it 'refuses unsafe or absent private identity before any container or repository mutation' do
    expect_command(catalog_check)
    expect_script('nest/build/check-stage3-paths.py')
      .with_params('arguments' => ['/nest/hosts/fixture-host', '/nest/hosts/fixture-host', 'fixture-host', ca_sha256, '--identity-reference', identity_reference])
      .error_with('msg' => 'Unsafe identity', 'kind' => 'fixture/identity')
    expect_command('podman rm -f fixture').not_be_called
    expect_command('podman volume rm -f fixture-frozen-repos').not_be_called
    expect(executor).not_to receive(:run_command).with(anything, %r{emerge }, anything, anything)
    expect(executor).not_to receive(:run_command).with(anything, %r{zsh -c .*rsync}, anything, anything)
    expect(run_plan('nest::build::stage3', options(3).merge('catalog_inputs' => catalog)).ok?).to be(false)
  end

  it 'retains the served Puppet environment path when frozen catalogs are not selected' do
    mocks(3)
    allow(executor).to receive(:run_command).and_call_original
    expect(executor).to receive(:run_command).with(anything, %r{puppet.*agent.*environment.*fixture.*env}, anything, anything).and_call_original
    expect_script('nest/build/freeze-repos.py').be_called_times(3)
    expect_command(catalog_check).not_be_called
    expect_script('nest/build/check-stage3-paths.py').not_be_called
    expect(run_plan('nest::build::stage3', options(3).merge('puppet_environment' => 'fixture-env')).ok?).to be(true)
  end

  it 'stops before identity apply or package build after stable capture failure' do
    allow_any_command
    allow_apply_prep
    expect_script('nest/build/freeze-repos.py')
    args = ['/private/fixture-host', '/nest/hosts/fixture-host', 'fixture-host', ca_sha256, '--identity-reference', identity_reference]
    expect_script('nest/build/check-stage3-paths.py').with_params('arguments' => args)
    expect_script('nest/build/check-stage3-paths.py')
      .with_params('arguments' => args + ['--install'])
      .error_with('msg' => 'Identity changed during capture', 'kind' => 'fixture/identity')
    expect(executor).not_to receive(:apply)
    expect(executor).not_to receive(:run_command).with(anything, %r{emerge }, anything, anything)
    expect(executor).not_to receive(:run_command).with(anything, %r{zsh -c .*rsync}, anything, anything)
    params = options(3).merge('catalog_inputs' => catalog, 'identityroot' => '/private/fixture-host')
    expect(run_plan('nest::build::stage3', params).ok?).to be(false)
  end

  it 'rejects frozen legacy rsync and malformed publication selections before commands' do
    expect(executor).not_to receive(:run_command)
    [{ 'deploy' => true }, { 'catalog_inputs' => nil }, { 'hostroot' => '/nest/hosts/fixture-host' },
     { 'root_publication' => publication.merge('extra' => true) },
     { 'root_publication' => publication.merge('staging_guid' => 'unknown') }].each do |override|
      expect(run_plan('nest::build::stage3', publication_options.merge(override)).ok?).to be(false)
    end
    expect(run_plan('nest::build::stage3', options(3).merge('catalog_inputs' => catalog, 'deploy' => true)).ok?).to be(false)
  end

  it 'admits placement before initialization and returns the completed stopped-root artifact without restart' do
    mocks(3)
    expect_script('nest/build/check-stage3-paths.py').be_called_times(4)
    expect_script('nest/build/freeze-repos.py').be_called_times(3)
    expect_command(catalog_check).be_called_times(4)
    expect_command("#{finish_command} --check")
    expect_command(finish_command).always_return('stdout' => root_artifact.to_json)
    expect_command('podman start fixture').be_called_times(1)
    expect_command('podman stop fixture').be_called_times(1)
    expect(executor).not_to receive(:run_command).with(anything, %r{zsh -c .*rsync}, anything, anything)
    result = run_plan('nest::build::stage3', publication_options)
    expect(result.ok?).to be(true)
    expect(result.value).to eq(root_artifact)
  end

  it 'stops before container removal when publication placement refuses' do
    expect_command(catalog_check)
    expect_script('nest/build/check-stage3-paths.py')
    expect_command("#{finish_command} --check").error_with('msg' => 'Wrong placement', 'kind' => 'fixture/placement')
    expect_command('podman rm -f fixture').not_be_called
    expect_command(finish_command).not_be_called
    expect(run_plan('nest::build::stage3', publication_options).ok?).to be(false)
  end

  it 'never invokes publication after a failed container stop' do
    mocks(3)
    expect_script('nest/build/check-stage3-paths.py').be_called_times(4)
    expect_script('nest/build/freeze-repos.py').be_called_times(3)
    expect_command("#{finish_command} --check")
    expect_command('podman stop fixture').error_with('msg' => 'Stop failed', 'kind' => 'fixture/stop')
    expect_command(finish_command).not_be_called
    expect(run_plan('nest::build::stage3', publication_options).ok?).to be(false)
  end

  it 'publishes the stopped native build on a distinct inventory-backed Joy target' do
    mocks(3)
    expect_script('nest/build/check-stage3-paths.py').be_called_times(4)
    expect_script('nest/build/freeze-repos.py').be_called_times(3)
    expect_command(catalog_check).be_called_times(4)
    helpers = '/private/receipts/stage3-helpers.fixture'
    expect_command('mktemp -d /private/receipts/stage3-helpers.XXXXXXXX')
      .with_targets('falcon').always_return('stdout' => "#{helpers}\n")
    ['check-stage3-root.py', 'publish-stage3-root.py', 'materialize-stage3-root.py',
     'finish-stage3-root.py', 'transfer-stage3-root.py'].each do |helper|
      expect_upload("nest/build/#{helper}").with_destination("#{helpers}/#{helper}").with_targets('falcon')
    end
    remote_finish = finish_command.sub('/opt/nest/files/build', helpers)
    expect_command("#{remote_finish} --check").with_targets('falcon')
    export_prefix = 'python3 /opt/nest/files/build/transfer-stage3-root.py'
    expect_command("#{export_prefix} export-check fixture /private/transfer/root.tar").with_targets('localhost')
    digests = { 'archive_digest' => "sha256:#{'c' * 64}", 'content_digest' => "sha256:#{'b' * 64}" }
    expect_command("#{export_prefix} export fixture /private/transfer/root.tar")
      .with_targets('localhost').always_return('stdout' => digests.to_json)
    receive = "python3 #{helpers}/transfer-stage3-root.py receive fixture /private/transfer/root.tar #{digests['archive_digest']} #{digests['content_digest']} " \
              "/private/staging 123 /private/receipts fixture-host fixture-release 456 sha256:#{'a' * 64} /private/fixture-host"
    expect_command(receive).with_targets('falcon').always_return('stdout' => root_artifact.to_json)
    expect_command(finish_command).not_be_called
    result = run_plan('nest::build::stage3', publication_options.merge(
      'root_publication' => publication.merge('target' => 'falcon', 'archive' => '/private/transfer/root.tar'),
    ))
    expect(result.ok?).to be(true), result.value.to_s
    expect(result.value).to eq(root_artifact)
  end

  it 'refuses changed publication paths rather than returning an accepted member' do
    mocks(3)
    expect_script('nest/build/check-stage3-paths.py').be_called_times(4)
    expect_script('nest/build/freeze-repos.py').be_called_times(3)
    expect_command("#{finish_command} --check")
    wrong = { 'root' => root_artifact['root'].merge('path' => '/wrong') }
    expect_command(finish_command).always_return('stdout' => wrong.to_json)
    expect(run_plan('nest::build::stage3', publication_options).ok?).to be(false)
  end
end
