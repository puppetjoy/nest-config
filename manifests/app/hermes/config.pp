class nest::app::hermes::config {
  $gitlab_url                       = $nest::app::hermes::gitlab_url
  $gitlab_token                     = $nest::app::hermes::gitlab_token
  $openai_api_key                   = $nest::app::hermes::openai_api_key
  $tavily_api_key                   = $nest::app::hermes::tavily_api_key
  $telegram_bot_token               = $nest::app::hermes::telegram_bot_token
  $telegram_allowed                 = $nest::app::hermes::telegram_allowed
  $telegram_home                    = $nest::app::hermes::telegram_home
  $model_provider                   = $nest::app::hermes::model_provider
  $model_name                       = $nest::app::hermes::model_name
  $model_base_url                   = $nest::app::hermes::model_base_url
  $auxiliary_provider               = $nest::app::hermes::auxiliary_provider
  $auxiliary_mini_model             = $nest::app::hermes::auxiliary_mini_model
  $compression_timeout              = $nest::app::hermes::compression_timeout
  $web_extract_timeout              = $nest::app::hermes::web_extract_timeout
  $dashboard_bind_host              = $nest::app::hermes::dashboard_bind_host
  $dashboard_oauth_client_id        = $nest::app::hermes::dashboard_oauth_client_id
  $dashboard_oauth_portal_url       = $nest::app::hermes::dashboard_oauth_portal_url
  $instances                        = $nest::app::hermes::instances
  $instance_secrets                 = $nest::app::hermes::instance_secrets

  $hermes_config_dir = "/home/${nest::user}/.config/hermes"
  $hermes_home_dir   = "/home/${nest::user}/.hermes"
  $profiles_dir      = "${hermes_home_dir}/profiles"
  $requests_dir      = "${hermes_home_dir}/agent-requests"

  file { $hermes_config_dir:
    ensure => directory,
    mode   => '0700',
    owner  => $nest::user,
    group  => $nest::user,
  }

  file { $hermes_home_dir:
    ensure => directory,
    mode   => '0700',
    owner  => $nest::user,
    group  => $nest::user,
  }

  file { $profiles_dir:
    ensure  => directory,
    mode    => '0700',
    owner   => $nest::user,
    group   => $nest::user,
    require => File[$hermes_home_dir],
  }

  file { "${profiles_dir}/tars":
    ensure  => absent,
    force   => true,
    recurse => true,
    require => File[$profiles_dir],
  }

  file { $requests_dir:
    ensure  => directory,
    mode    => '0700',
    owner   => $nest::user,
    group   => $nest::user,
    require => File[$hermes_home_dir],
  }

  [
    'sessions',
    'memories',
    'cron',
    'logs',
    'cache',
    'state-snapshots',
    'config.yaml',
    'managed-config.yaml',
    'honcho.json',
    'SOUL.md',
    '.env',
  ].each |String[1] $default_profile_path| {
    file { "${hermes_home_dir}/${default_profile_path}":
      ensure  => absent,
      force   => true,
      recurse => true,
    }
  }

  $instances.each |String[1] $instance_name, Hash $instance_config| {
    $secrets = $instance_secrets[$instance_name] ? {
      undef   => {},
      default => $instance_secrets[$instance_name],
    }

    $config = $instance_config + $secrets

    $profile                 = pick($config['profile'], $instance_name)
    $display_name            = pick($config['display_name'], $instance_name)
    $instance_gitlab_enabled = pick($config['gitlab_enabled'], false)
    $instance_gitlab_token   = $instance_gitlab_enabled ? {
      true    => $config['gitlab_token'] ? {
        undef   => $gitlab_token,
        default => $config['gitlab_token'],
      },
      default => undef,
    }
    $instance_tavily_api_key    = $config['tavily_api_key'] ? {
      undef   => $tavily_api_key,
      default => $config['tavily_api_key'],
    }
    $instance_openai_api_key    = $config['openai_api_key'] ? {
      undef   => $openai_api_key,
      default => $config['openai_api_key'],
    }
    $instance_telegram_token    = $config['telegram_bot_token'] ? {
      undef   => $telegram_bot_token,
      default => $config['telegram_bot_token'],
    }
    $instance_telegram_enabled  = pick($config['telegram_enabled'], true)
    $instance_telegram_allowed  = pick($config['telegram_allowed'], $telegram_allowed)
    $instance_telegram_home     = pick($config['telegram_home'], $telegram_home)
    $instance_model_provider    = pick($config['model_provider'], $model_provider)
    $instance_model_name        = pick($config['model_name'], $model_name)
    $instance_model_base_url    = pick($config['model_base_url'], $model_base_url)
    $instance_aux_provider      = pick($config['auxiliary_provider'], $auxiliary_provider)
    $instance_aux_model         = pick($config['auxiliary_mini_model'], $auxiliary_mini_model)
    $instance_compress_timeout  = pick($config['compression_timeout'], $compression_timeout)
    $instance_extract_timeout   = pick($config['web_extract_timeout'], $web_extract_timeout)
    $instance_dashboard_enabled = pick($config['dashboard_enabled'], false)
    $instance_dashboard_bind    = pick($config['dashboard_bind_host'], $dashboard_bind_host)
    $instance_dashboard_port    = pick($config['dashboard_port'], 9119)
    $instance_dashboard_url     = pick($config['dashboard_public_url'], "https://${instance_name}.eyrie")
    $instance_oauth_client_id   = $config['dashboard_oauth_client_id'] ? {
      undef   => $dashboard_oauth_client_id,
      default => $config['dashboard_oauth_client_id'],
    }
    $instance_oauth_portal_url  = $config['dashboard_oauth_portal_url'] ? {
      undef   => $dashboard_oauth_portal_url,
      default => $config['dashboard_oauth_portal_url'],
    }
    $instance_gateway_enabled   = pick($config['gateway_enabled'], true)
    $instance_honcho_base_url   = pick($config['honcho_base_url'], 'https://honcho.eyrie')
    $instance_honcho_workspace  = pick($config['honcho_workspace'], 'hermes')
    $instance_honcho_user_peer  = pick($config['honcho_user_peer'], 'joy')
    $instance_honcho_ai_peer    = pick($config['honcho_ai_peer'], $instance_name)
    $instance_soul_content      = $config['soul_content']
    $instance_toolsets          = $config['telegram_toolsets']
    $instance_google_workspace  = pick($config['google_workspace_enabled'], false)
    $instance_clone_default     = pick($config['clone_from_default'], false)

    nest::lib::hermes { $instance_name:
      profile                    => $profile,
      display_name               => $display_name,
      install_dir                => $nest::app::hermes::install_dir,
      user                       => $nest::user,
      gitlab_url                 => $gitlab_url,
      gitlab_token               => $instance_gitlab_token,
      gitlab_enabled             => $instance_gitlab_enabled,
      openai_api_key             => $instance_openai_api_key,
      tavily_api_key             => $instance_tavily_api_key,
      telegram_bot_token         => $instance_telegram_token,
      telegram_enabled           => $instance_telegram_enabled,
      telegram_allowed           => $instance_telegram_allowed,
      telegram_home              => $instance_telegram_home,
      model_provider             => $instance_model_provider,
      model_name                 => $instance_model_name,
      model_base_url             => $instance_model_base_url,
      auxiliary_provider         => $instance_aux_provider,
      auxiliary_mini_model       => $instance_aux_model,
      compression_timeout        => $instance_compress_timeout,
      web_extract_timeout        => $instance_extract_timeout,
      dashboard_enabled          => $instance_dashboard_enabled,
      dashboard_bind_host        => $instance_dashboard_bind,
      dashboard_port             => $instance_dashboard_port,
      dashboard_public_url       => $instance_dashboard_url,
      dashboard_oauth_client_id  => $instance_oauth_client_id,
      dashboard_oauth_portal_url => $instance_oauth_portal_url,
      gateway_enabled            => $instance_gateway_enabled,
      honcho_base_url            => $instance_honcho_base_url,
      honcho_workspace           => $instance_honcho_workspace,
      honcho_user_peer           => $instance_honcho_user_peer,
      honcho_ai_peer             => $instance_honcho_ai_peer,
      soul_content               => $instance_soul_content,
      telegram_toolsets          => $instance_toolsets,
      google_workspace_enabled   => $instance_google_workspace,
      clone_from_default         => $instance_clone_default,
    }
  }
}
