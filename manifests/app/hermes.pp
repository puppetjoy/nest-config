class nest::app::hermes (
  Stdlib::Absolutepath           $install_dir                 = '/opt/hermes-agent',
  String[1]                      $git_url                     = 'https://gitlab.joyfullee.me/nest/forks/hermes-agent.git',
  String[1]                      $git_ref                     = 'main',
  Optional[String[1]]            $git_commit                  = undef,
  Stdlib::Absolutepath           $ca_bundle_file              = '/etc/ssl/certs/ca-certificates.crt',
  String[1]                      $broker_git_url              = 'https://gitlab.joyfullee.me/nest/hermes-agent-request-broker.git',
  String[1]                      $broker_git_ref              = 'main',
  String[1]                      $agent_request_kanban_board  = 'agent-requests',
  String[1]                      $gitlab_url                  = 'https://gitlab.joyfullee.me',
  Optional[Sensitive[String[1]]] $gitlab_token                = undef,
  Optional[Sensitive[String[1]]] $tavily_api_key              = undef,
  Optional[Sensitive[String[1]]] $telegram_bot_token          = undef,
  Optional[Sensitive[String[1]]] $voice_tools_openai_key      = undef,
  Optional[Sensitive[String[1]]] $codex_oauth_pool_json       = undef,
  String[1]                      $telegram_allowed            = '8756212310',
  String[1]                      $telegram_home               = '8756212310',
  Optional[String[1]]            $telegram_bot_username       = undef,
  Optional[String[1]]            $telegram_bot_id             = undef,
  String[1]                      $model_provider              = 'openai-codex',
  String[1]                      $model_name                  = 'gpt-5.5',
  String[1]                      $model_base_url              = 'https://chatgpt.com/backend-api/codex',
  Hash[String[1], Any]           $providers                   = {},
  String[1]                      $auxiliary_provider          = 'openai-codex',
  String[1]                      $auxiliary_mini_model        = 'gpt-5.4-mini',
  Optional[String[1]]            $image_gen_provider          = undef,
  Optional[String[1]]            $image_gen_model             = undef,
  Integer[1]                     $compression_timeout         = 120,
  Integer[1]                     $web_extract_timeout         = 360,
  String[1]                      $dashboard_bind_host         = '0.0.0.0',
  Optional[String[1]]            $dashboard_oauth_client_id   = undef,
  Optional[String[1]]            $dashboard_oauth_portal_url  = undef,
  Hash[String[1], Any]           $terminal                    = {},
  Hash[String[1], String[1]]     $environment                 = {},
  Array[String[1]]               $toolsets                    = [
    'agent_directory',
    'agent_requests',
    'browser',
    'clarify',
    'code_execution',
    'computer_use',
    'cronjob',
    'delegation',
    'file',
    'google_workspace',
    'image_gen',
    'kanban',
    'memory',
    'messaging',
    'oauth_browser',
    'session_search',
    'shopping_browser',
    'skills',
    'terminal',
    'todo',
    'tts',
    'vision',
    'web',
  ],
  Hash[String[1], Hash]          $instances                   = {},
  Hash[String[1], Hash]          $instance_secrets            = {},
) {
  case $facts['os']['family'] {
    'Gentoo': {
      contain nest::app::hermes::install
      contain nest::app::hermes::service
      contain nest::app::hermes::config

      Class['nest::app::hermes::install']
      -> Class['nest::app::hermes::service']
      -> Class['nest::app::hermes::config']
    }
  }
}
