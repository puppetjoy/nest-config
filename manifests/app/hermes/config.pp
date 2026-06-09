class nest::app::hermes::config {
  $gitlab_url                       = $nest::app::hermes::gitlab_url
  $gitlab_token                     = $nest::app::hermes::gitlab_token
  $openai_api_key                   = $nest::app::hermes::openai_api_key
  $tavily_api_key                   = $nest::app::hermes::tavily_api_key
  $telegram_bot_token               = $nest::app::hermes::telegram_bot_token
  $codex_oauth_slots                = $nest::app::hermes::codex_oauth_slots
  $codex_oauth_default_label        = $nest::app::hermes::codex_oauth_default_label
  $telegram_allowed                 = $nest::app::hermes::telegram_allowed
  $telegram_home                    = $nest::app::hermes::telegram_home
  $telegram_bot_username            = $nest::app::hermes::telegram_bot_username
  $telegram_bot_id                  = $nest::app::hermes::telegram_bot_id
  $model_provider                   = $nest::app::hermes::model_provider
  $model_name                       = $nest::app::hermes::model_name
  $model_base_url                   = $nest::app::hermes::model_base_url
  $auxiliary_provider               = $nest::app::hermes::auxiliary_provider
  $auxiliary_mini_model             = $nest::app::hermes::auxiliary_mini_model
  $image_gen_provider               = $nest::app::hermes::image_gen_provider
  $image_gen_model                  = $nest::app::hermes::image_gen_model
  $compression_timeout              = $nest::app::hermes::compression_timeout
  $web_extract_timeout              = $nest::app::hermes::web_extract_timeout
  $dashboard_bind_host              = $nest::app::hermes::dashboard_bind_host
  $dashboard_oauth_client_id        = $nest::app::hermes::dashboard_oauth_client_id
  $dashboard_oauth_portal_url       = $nest::app::hermes::dashboard_oauth_portal_url
  $toolsets                         = $nest::app::hermes::toolsets
  $agent_request_kanban_board       = $nest::app::hermes::agent_request_kanban_board
  $instances                        = $nest::app::hermes::instances
  $instance_secrets                 = $nest::app::hermes::instance_secrets

  $hermes_config_dir       = "/home/${nest::user}/.config/hermes"
  $hermes_home_dir         = "/home/${nest::user}/.hermes"
  $profiles_dir            = "${hermes_home_dir}/profiles"
  $codex_auth_manager_path = "${nest::app::hermes::install_dir}/bin/hermes-share-codex-auth"
  $codex_auth_slots_dir    = "${hermes_home_dir}/codex-auth"
  $codex_auth_slots_path   = "${codex_auth_slots_dir}/slots.json"
  $codex_auth_active_path  = "${codex_auth_slots_dir}/active-label"

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

  file { $codex_auth_slots_dir:
    ensure  => directory,
    mode    => '0700',
    owner   => $nest::user,
    group   => $nest::user,
    require => File[$hermes_home_dir],
  }

  if !empty($codex_oauth_slots) {
    file { $codex_auth_slots_path:
      ensure    => file,
      mode      => '0600',
      owner     => $nest::user,
      group     => $nest::user,
      content   => Sensitive(stdlib::to_json({ 'slots' => $codex_oauth_slots })),
      show_diff => false,
      require   => File[$codex_auth_slots_dir],
    }

    file { $codex_auth_active_path:
      ensure  => file,
      mode    => '0600',
      owner   => $nest::user,
      group   => $nest::user,
      content => "${codex_oauth_default_label}\n",
      replace => false,
      require => File[$codex_auth_slots_dir],
    }
  }

  $codex_auth_slots_args = empty($codex_oauth_slots) ? {
    true    => '',
    default => "--slots-file ${codex_auth_slots_path} --active-file ${codex_auth_active_path} --default-label ${codex_oauth_default_label}",
  }

  $codex_auth_profiles = $instances.map |String[1] $instance_name, Hash $instance_config| {
    pick($instance_config['profile'], $instance_name)
  }

  if $codex_auth_profiles.length > 0 {
    $codex_auth_profile_args = $codex_auth_profiles.join(' ')
    $codex_auth_require = empty($codex_oauth_slots) ? {
      true    => [
        File[$hermes_home_dir],
        File[$profiles_dir],
        File[$codex_auth_manager_path],
      ],
      default => [
        File[$hermes_home_dir],
        File[$profiles_dir],
        File[$codex_auth_manager_path],
        File[$codex_auth_slots_path],
        File[$codex_auth_active_path],
      ],
    }

    exec { 'share_hermes_codex_auth':
      command     => "${codex_auth_manager_path} apply --home /home/${nest::user} ${codex_auth_slots_args} ${codex_auth_profile_args}",
      unless      => "${codex_auth_manager_path} check --home /home/${nest::user} ${codex_auth_slots_args} ${codex_auth_profile_args}",
      user        => $nest::user,
      environment => ["HOME=/home/${nest::user}"],
      require     => $codex_auth_require,
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
    $instance_profile_icon   = $config['profile_icon']
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
    $instance_telegram_bot_username = $config['telegram_bot_username'] ? {
      undef   => $telegram_bot_username,
      default => $config['telegram_bot_username'],
    }
    $instance_telegram_bot_id = $config['telegram_bot_id'] ? {
      undef   => $telegram_bot_id,
      default => $config['telegram_bot_id'],
    }
    $instance_model_provider    = pick($config['model_provider'], $model_provider)
    $instance_model_name        = pick($config['model_name'], $model_name)
    $instance_model_base_url    = pick($config['model_base_url'], $model_base_url)
    $instance_aux_provider      = pick($config['auxiliary_provider'], $auxiliary_provider)
    $instance_aux_model         = pick($config['auxiliary_mini_model'], $auxiliary_mini_model)
    $instance_image_provider    = $config['image_gen_provider'] ? {
      undef   => $image_gen_provider,
      default => $config['image_gen_provider'],
    }
    $instance_image_model       = $config['image_gen_model'] ? {
      undef   => $image_gen_model,
      default => $config['image_gen_model'],
    }
    $instance_compress_timeout  = pick($config['compression_timeout'], $compression_timeout)
    $instance_extract_timeout   = pick($config['web_extract_timeout'], $web_extract_timeout)
    $instance_approval_mode     = pick($config['approval_mode'], 'manual')
    $instance_dashboard_enabled = pick($config['dashboard_enabled'], false)
    $instance_dashboard_bind    = pick($config['dashboard_bind_host'], $dashboard_bind_host)
    $instance_dashboard_port    = pick($config['dashboard_port'], 9119)
    $instance_dashboard_url     = pick($config['dashboard_public_url'], "https://${instance_name}.eyrie")
    $instance_ssh_auth_sock     = $config['ssh_auth_sock']
    $instance_dashboard_theme   = $config['dashboard_theme']
    $instance_oauth_client_id   = $config['dashboard_oauth_client_id'] ? {
      undef   => $dashboard_oauth_client_id,
      default => $config['dashboard_oauth_client_id'],
    }
    $instance_oauth_portal_url  = $config['dashboard_oauth_portal_url'] ? {
      undef   => $dashboard_oauth_portal_url,
      default => $config['dashboard_oauth_portal_url'],
    }
    $instance_gateway_enabled   = pick($config['gateway_enabled'], true)
    $instance_kanban_dispatch   = pick($config['kanban_dispatch_in_gateway'], true)
    $instance_honcho_base_url   = pick($config['honcho_base_url'], 'https://honcho.eyrie')
    $instance_honcho_workspace  = pick($config['honcho_workspace'], 'hermes')
    $instance_honcho_user_peer  = pick($config['honcho_user_peer'], 'joy')
    $instance_honcho_ai_peer    = pick($config['honcho_ai_peer'], $instance_name)
    $instance_soul_content      = $config['soul_content']
    $instance_skin_name         = $config['skin_name']
    $instance_skin_content      = $config['skin_content']
    $instance_skin_hero_source  = $config['skin_banner_hero_source']
    $instance_toolsets          = $config['toolsets'] ? {
      undef   => $config['telegram_toolsets'] ? {
        undef   => $toolsets,
        default => $config['telegram_toolsets'],
      },
      default => $config['toolsets'],
    }
    $instance_profile_toolsets  = pick($config['profile_toolsets'], ['hermes-cli', 'kanban'])
    $instance_directory_enabled = pick($config['agent_directory_enabled'], true)
    $instance_directory_board   = pick($config['agent_directory_board'], 'agent-directory')
    $instance_directory_touch   = pick($config['agent_directory_touch'], 3600)
    $instance_google_workspace  = pick($config['google_workspace_enabled'], false)
    $instance_voice_auto_tts    = pick($config['voice_auto_tts'], false)
    $instance_stt_enabled       = pick($config['stt_enabled'], $instance_voice_auto_tts)
    $instance_stt_provider      = pick($config['stt_provider'], 'openai')
    $instance_stt_model         = pick($config['stt_model'], 'gpt-4o-mini-transcribe')
    $instance_tts_provider      = pick($config['tts_provider'], 'openai')
    $instance_tts_openai_model  = pick($config['tts_openai_model'], 'gpt-4o-mini-tts')
    $instance_tts_openai_voice  = pick($config['tts_openai_voice'], 'alloy')
    $instance_kubeconfig_path   = $config['kubeconfig_path']
    $instance_kubeconfig        = $config['kubeconfig_content']
    $instance_extra_packages    = pick($config['extra_packages'], [])
    $instance_release_digest    = pick($config['release_digest_enabled'], false)

    nest::lib::hermes { $instance_name:
      profile                    => $profile,
      display_name               => $display_name,
      profile_icon               => $instance_profile_icon,
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
      telegram_bot_username      => $instance_telegram_bot_username,
      telegram_bot_id            => $instance_telegram_bot_id,
      model_provider             => $instance_model_provider,
      model_name                 => $instance_model_name,
      model_base_url             => $instance_model_base_url,
      auxiliary_provider         => $instance_aux_provider,
      auxiliary_mini_model       => $instance_aux_model,
      image_gen_provider         => $instance_image_provider,
      image_gen_model            => $instance_image_model,
      compression_timeout        => $instance_compress_timeout,
      web_extract_timeout        => $instance_extract_timeout,
      approval_mode              => $instance_approval_mode,
      dashboard_enabled          => $instance_dashboard_enabled,
      dashboard_bind_host        => $instance_dashboard_bind,
      dashboard_port             => $instance_dashboard_port,
      dashboard_public_url       => $instance_dashboard_url,
      ssh_auth_sock              => $instance_ssh_auth_sock,
      dashboard_theme            => $instance_dashboard_theme,
      dashboard_oauth_client_id  => $instance_oauth_client_id,
      dashboard_oauth_portal_url => $instance_oauth_portal_url,
      agent_request_kanban_board => $agent_request_kanban_board,
      kanban_dispatch_in_gateway => $instance_kanban_dispatch,
      gateway_enabled            => $instance_gateway_enabled,
      honcho_base_url            => $instance_honcho_base_url,
      honcho_workspace           => $instance_honcho_workspace,
      honcho_user_peer           => $instance_honcho_user_peer,
      honcho_ai_peer             => $instance_honcho_ai_peer,
      soul_content               => $instance_soul_content,
      skin_name                  => $instance_skin_name,
      skin_content               => $instance_skin_content,
      skin_banner_hero_source    => $instance_skin_hero_source,
      profile_toolsets           => $instance_profile_toolsets,
      toolsets                   => $instance_toolsets,
      agent_directory_enabled    => $instance_directory_enabled,
      agent_directory_board      => $instance_directory_board,
      agent_directory_touch      => $instance_directory_touch,
      google_workspace_enabled   => $instance_google_workspace,
      voice_auto_tts             => $instance_voice_auto_tts,
      stt_enabled                => $instance_stt_enabled,
      stt_provider               => $instance_stt_provider,
      stt_model                  => $instance_stt_model,
      tts_provider               => $instance_tts_provider,
      tts_openai_model           => $instance_tts_openai_model,
      tts_openai_voice           => $instance_tts_openai_voice,
      kubeconfig_path            => $instance_kubeconfig_path,
      kubeconfig_content         => $instance_kubeconfig,
      extra_packages             => $instance_extra_packages,
      release_digest_enabled     => $instance_release_digest,
    }
  }
}
