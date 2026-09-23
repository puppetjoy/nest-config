require 'spec_helper'
require 'yaml'

RSpec.describe 'Quill Hermes work profile' do
  let(:repo_root) { File.expand_path('../..', __dir__) }
  let(:owl_data) { YAML.safe_load_file(File.join(repo_root, 'data/host/owl.yaml'), aliases: true) }
  let(:quill) { owl_data.fetch('nest::app::hermes::instances').fetch('quill') }
  let(:config_manifest) { File.read(File.join(repo_root, 'manifests/app/hermes/config.pp')) }
  let(:hermes_define) { File.read(File.join(repo_root, 'manifests/lib/hermes.pp')) }

  it 'keeps the work identity and runtime isolated' do
    expect(quill).to include(
      'display_name' => 'Quill',
      'profile_icon' => '🪶',
      'model_provider' => 'copilot',
      'model_name' => 'gpt-6-luna',
      'model_api_mode' => 'codex_responses',
      'agent_reasoning_effort' => 'max',
      'inherit_shared_credentials' => false,
      'honcho_workspace' => 'hermes',
      'honcho_user_peer' => 'joy',
      'honcho_ai_peer' => 'quill',
      'telegram_bot_username' => 'quillpuppetbot',
      'telegram_bot_id' => '8805292444',
    )
    expect(quill).not_to have_key('ssh_private_key')
    expect(quill).not_to have_key('kubeconfig_content')
    expect(quill).not_to have_key('gitlab_token')
    expect(quill).not_to have_key('image_gen_provider')
    expect(quill.fetch('kanban_dispatch_in_gateway')).to be(false)
    expect(quill.fetch('toolsets')).not_to include('secure_browser', 'computer_use', 'google_workspace')
  end

  it 'runs file and terminal tools on hawk over the runtime SSH agent' do
    expect(quill.fetch('terminal')).to include(
      'backend' => 'ssh',
      'cwd' => '/home/joy',
      'ssh_host' => 'hawk',
      'ssh_user' => 'joy',
      'ssh_port' => 22,
      'ssh_persistent' => true,
      'persistent_shell' => true,
    )
    expect(quill.fetch('environment')).to include(
      'TERMINAL_SSH_HOST' => 'hawk',
      'TERMINAL_SSH_USER' => 'joy',
      'TERMINAL_SSH_PORT' => '22',
    )
    expect(quill.fetch('ssh_auth_sock')).to eq('/run/user/1000/ssh-agent.socket')
    expect(quill.fetch('runtime_env_keys')).to eq(['COPILOT_GITHUB_TOKEN'])
  end

  it 'matches Star tool-execution privilege without adding a command allowlist' do
    expect(quill.fetch('approval_mode')).to eq('off')
    expect(quill).not_to have_key('command_allowlist')
    expect(quill.fetch('enabled_plugins', [])).not_to include('quill-command-policy')
  end

  it 'gates every shared credential path and cleans Codex shadows for Quill' do
    expect(config_manifest).to include('$inherit_shared_credentials')
    expect(config_manifest).to include('gitlab_joy_token           => $instance_gitlab_joy_token')
    expect(config_manifest).to include('$credential_cleanup_profiles = $instances.map')
    expect(config_manifest).not_to include('$instances.filter')
  end

  it 'source-manages the Copilot Responses mode and max reasoning' do
    expect(config_manifest).to include('model_api_mode             => $instance_model_api_mode')
    expect(config_manifest).to include('agent_reasoning_effort     => $instance_agent_reasoning')
    expect(hermes_define).to include("default => { 'api_mode' => $model_api_mode }")
    expect(hermes_define).to include("default => { 'reasoning_effort' => $agent_reasoning_effort }")
  end

  it 'uses GPT-6 Luna with provider-default reasoning for every helper route' do
    expect(quill).to include(
      'auxiliary_provider' => 'copilot',
      'auxiliary_compress_model' => 'gpt-6-luna',
      'auxiliary_extract_model' => 'gpt-6-luna',
      'auxiliary_title_model' => 'gpt-6-luna',
      'delegation_provider' => 'copilot',
      'delegation_model' => 'gpt-6-luna',
    )
    expect(quill).not_to have_key('auxiliary_reasoning_effort')
    expect(quill).not_to have_key('delegation_reasoning_effort')
  end

  it 'uses the selected local speech voice and source-managed media' do
    expect(quill).to include(
      'stt_provider' => 'voice-speech',
      'tts_provider' => 'voice-speech',
      'tts_voice_speech_voice' => 'bm_fable',
      'tts_voice_speech_model' => 'kokoro',
      'skin_name' => 'quill-puppet-dusk',
      'profile_avatar_source' => 'nest/app/hermes/personas/quill-telegram-avatar-640.jpg',
    )

    expect(File).to exist(File.join(repo_root, 'files/app/hermes/skins/quill-puppet-dusk-banner-hero.ansi'))
    expect(File).to exist(File.join(repo_root, 'files/app/hermes/personas/quill-telegram-avatar-640.jpg'))
  end
end
