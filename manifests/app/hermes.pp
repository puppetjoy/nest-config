class nest::app::hermes (
  Stdlib::Absolutepath           $install_dir                 = '/opt/hermes-agent',
  String[1]                      $git_url                     = 'https://github.com/NousResearch/hermes-agent.git',
  String[1]                      $git_ref                     = 'main',
  String[1]                      $gitlab_url                  = 'https://gitlab.joyfullee.me',
  Optional[Sensitive[String[1]]] $gitlab_token                = undef,
  Optional[Sensitive[String[1]]] $tavily_api_key              = undef,
  Optional[Sensitive[String[1]]] $telegram_bot_token          = undef,
  String[1]                      $telegram_allowed            = '8756212310',
  String[1]                      $telegram_home               = '8756212310',
  String[1]                      $model_provider              = 'openai-codex',
  String[1]                      $model_name                  = 'gpt-5.5',
  String[1]                      $model_base_url              = 'https://chatgpt.com/backend-api/codex',
  String[1]                      $auxiliary_provider          = 'openai-codex',
  String[1]                      $auxiliary_mini_model        = 'gpt-5.4-mini',
  Integer[1]                     $compression_timeout         = 120,
  Integer[1]                     $web_extract_timeout         = 360,
  Boolean                        $dashboard_enabled           = false,
  String[1]                      $dashboard_bind_host         = '0.0.0.0',
  Stdlib::Port                   $dashboard_port              = 9119,
  String[1]                      $dashboard_public_url        = 'https://talon.eyrie',
  Optional[String[1]]            $dashboard_oauth_client_id   = undef,
  Optional[String[1]]            $dashboard_oauth_portal_url  = undef,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      Class['nest::app::hermes::install']
      -> Class['nest::app::hermes::config']
      -> Class['nest::app::hermes::service']

      class { 'nest::app::hermes::install':
        install_dir => $install_dir,
        git_url     => $git_url,
        git_ref     => $git_ref,
      }

      class { 'nest::app::hermes::config':
        install_dir                => $install_dir,
        gitlab_url                 => $gitlab_url,
        gitlab_token               => $gitlab_token,
        tavily_api_key             => $tavily_api_key,
        telegram_bot_token         => $telegram_bot_token,
        telegram_allowed           => $telegram_allowed,
        telegram_home              => $telegram_home,
        model_provider             => $model_provider,
        model_name                 => $model_name,
        model_base_url             => $model_base_url,
        auxiliary_provider         => $auxiliary_provider,
        auxiliary_mini_model       => $auxiliary_mini_model,
        compression_timeout        => $compression_timeout,
        web_extract_timeout        => $web_extract_timeout,
        dashboard_public_url       => $dashboard_public_url,
        dashboard_oauth_client_id  => $dashboard_oauth_client_id,
        dashboard_oauth_portal_url => $dashboard_oauth_portal_url,
      }

      class { 'nest::app::hermes::service':
        install_dir               => $install_dir,
        dashboard_enabled         => $dashboard_enabled,
        dashboard_bind_host       => $dashboard_bind_host,
        dashboard_port            => $dashboard_port,
        dashboard_oauth_client_id => $dashboard_oauth_client_id,
      }
    }
  }
}
