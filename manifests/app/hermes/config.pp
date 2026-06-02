class nest::app::hermes::config {
  $install_dir                      = $nest::app::hermes::install_dir
  $gitlab_url                       = $nest::app::hermes::gitlab_url
  $gitlab_token                     = $nest::app::hermes::gitlab_token
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
  $dashboard_public_url             = $nest::app::hermes::dashboard_public_url
  $dashboard_oauth_client_id        = $nest::app::hermes::dashboard_oauth_client_id
  $dashboard_oauth_portal_url       = $nest::app::hermes::dashboard_oauth_portal_url
  $venv_dir                         = "${install_dir}/venv"
  $venv_python                      = "${venv_dir}/bin/python"
  $hermes_config_dir                = "/home/${nest::user}/.config/hermes"
  $hermes_home_dir                  = "/home/${nest::user}/.hermes"
  $hermes_env_path                  = "${hermes_home_dir}/.env"
  $hermes_config_path               = "${hermes_home_dir}/config.yaml"
  $hermes_managed_config_path       = "${hermes_home_dir}/managed-config.yaml"
  $hermes_config_manager_path       = "${install_dir}/bin/manage-hermes-config"
  $hermes_honcho_config_path        = "${hermes_home_dir}/honcho.json"
  $dashboard_oauth_client_id_value  = $dashboard_oauth_client_id ? {
    undef   => '',
    default => $dashboard_oauth_client_id,
  }
  $dashboard_oauth_portal_url_value = $dashboard_oauth_portal_url ? {
    undef   => '',
    default => $dashboard_oauth_portal_url,
  }

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

  file { $hermes_env_path:
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    require => File[$hermes_home_dir],
  }


  file { $hermes_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    require => File[$hermes_home_dir],
  }

  if $gitlab_token {
    file_line { 'hermes-env-gitlab-url':
      path    => $hermes_env_path,
      line    => "GITLAB_URL=${gitlab_url}",
      match   => '^GITLAB_URL=',
      require => File[$hermes_env_path],
    }

    file_line { 'hermes-env-gitlab-token':
      path    => $hermes_env_path,
      line    => Sensitive("GITLAB_TOKEN=${gitlab_token.unwrap}"),
      match   => '^GITLAB_TOKEN=',
      require => File[$hermes_env_path],
    }
  } else {
    file_line { 'hermes-env-gitlab-url':
      ensure            => absent,
      path              => $hermes_env_path,
      match             => '^GITLAB_URL=',
      match_for_absence => true,
      multiple          => true,
      require           => File[$hermes_env_path],
    }

    file_line { 'hermes-env-gitlab-token':
      ensure            => absent,
      path              => $hermes_env_path,
      match             => '^GITLAB_TOKEN=',
      match_for_absence => true,
      multiple          => true,
      require           => File[$hermes_env_path],
    }
  }

  if $tavily_api_key {
    file_line { 'hermes-env-tavily-api-key':
      path    => $hermes_env_path,
      line    => Sensitive("TAVILY_API_KEY=${tavily_api_key.unwrap}"),
      match   => '^TAVILY_API_KEY=',
      require => File[$hermes_env_path],
    }
  } else {
    file_line { 'hermes-env-tavily-api-key':
      ensure            => absent,
      path              => $hermes_env_path,
      match             => '^TAVILY_API_KEY=',
      match_for_absence => true,
      multiple          => true,
      require           => File[$hermes_env_path],
    }
  }

  if $telegram_bot_token {
    file_line { 'hermes-env-telegram-bot-token':
      path    => $hermes_env_path,
      line    => Sensitive("TELEGRAM_BOT_TOKEN=${telegram_bot_token.unwrap}"),
      match   => '^TELEGRAM_BOT_TOKEN=',
      require => File[$hermes_env_path],
    }

    file_line { 'hermes-env-telegram-allowed-users':
      path    => $hermes_env_path,
      line    => "TELEGRAM_ALLOWED_USERS=${telegram_allowed}",
      match   => '^TELEGRAM_ALLOWED_USERS=',
      require => File[$hermes_env_path],
    }

    file_line { 'hermes-env-telegram-home-channel':
      path    => $hermes_env_path,
      line    => "TELEGRAM_HOME_CHANNEL=${telegram_home}",
      match   => '^TELEGRAM_HOME_CHANNEL=',
      require => File[$hermes_env_path],
    }
  } else {
    file_line { 'hermes-env-telegram-bot-token':
      ensure            => absent,
      path              => $hermes_env_path,
      match             => '^TELEGRAM_BOT_TOKEN=',
      match_for_absence => true,
      multiple          => true,
      require           => File[$hermes_env_path],
    }

    file_line { 'hermes-env-telegram-allowed-users':
      ensure            => absent,
      path              => $hermes_env_path,
      match             => '^TELEGRAM_ALLOWED_USERS=',
      match_for_absence => true,
      multiple          => true,
      require           => File[$hermes_env_path],
    }

    file_line { 'hermes-env-telegram-home-channel':
      ensure            => absent,
      path              => $hermes_env_path,
      match             => '^TELEGRAM_HOME_CHANNEL=',
      match_for_absence => true,
      multiple          => true,
      require           => File[$hermes_env_path],
    }
  }

  file { "${install_dir}/bin":
    ensure  => directory,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File[$install_dir],
  }

  file { $hermes_config_manager_path:
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    source  => 'puppet:///modules/nest/hermes/manage-config.py',
    require => File["${install_dir}/bin"],
  }

  file { $hermes_managed_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("YAML"),
      ---
      model:
        provider: "${model_provider}"
        default: "${model_name}"
        base_url: "${model_base_url}"
      web:
        backend: tavily
        search_backend: tavily
      auxiliary:
        compression:
          provider: "${auxiliary_provider}"
          model: "${auxiliary_mini_model}"
          timeout: ${compression_timeout}
        web_extract:
          provider: "${auxiliary_provider}"
          model: "${auxiliary_mini_model}"
          timeout: ${web_extract_timeout}
      platform_toolsets:
        telegram:
          - browser
          - clarify
          - code_execution
          - computer_use
          - cronjob
          - delegation
          - file
          - image_gen
          - memory
          - messaging
          - session_search
          - skills
          - terminal
          - todo
          - tts
          - vision
          - web
      display:
        tool_progress: all
        tool_progress_command: true
        platforms:
          telegram:
            tool_progress: all
            tool_preview_length: 500
      memory:
        provider: honcho
      dashboard:
        public_url: "${dashboard_public_url}"
        oauth:
          client_id: "${dashboard_oauth_client_id_value}"
          portal_url: "${dashboard_oauth_portal_url_value}"
      | YAML
    require => File[$hermes_home_dir],
  }

  exec { 'configure_hermes_managed_config':
    command     => "${venv_python} ${hermes_config_manager_path} apply ${hermes_config_path} ${hermes_managed_config_path}",
    unless      => "${venv_python} ${hermes_config_manager_path} check ${hermes_config_path} ${hermes_managed_config_path}",
    user        => $nest::user,
    environment => ["HOME=/home/${nest::user}"],
    require     => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_honcho_deps'],
      File[$hermes_config_path],
      File[$hermes_config_manager_path],
      File[$hermes_managed_config_path],
      File[$hermes_honcho_config_path],
    ],
  }

  file_line { 'hermes-env-honcho-api-key':
    ensure            => absent,
    path              => $hermes_env_path,
    match             => '^HONCHO_API_KEY=',
    match_for_absence => true,
    multiple          => true,
    require           => File[$hermes_env_path],
  }

  file { $hermes_honcho_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $nest::user,
    group   => $nest::user,
    content => @("JSON"),
      {
        "dialecticCadence": 2,
        "baseUrl": "https://honcho.eyrie",
        "hosts": {
          "hermes": {
            "workspace": "hermes",
            "peerName": "joy",
            "aiPeer": "talon",
            "enabled": true,
            "pinPeerName": true,
            "observationMode": "directional",
            "writeFrequency": "async",
            "recallMode": "hybrid",
            "dialecticCadence": 2,
            "dialecticReasoningLevel": "low",
            "sessionStrategy": "per-session",
            "saveMessages": true
          }
        }
      }
      | JSON
    require => File[$hermes_home_dir],
  }
}
