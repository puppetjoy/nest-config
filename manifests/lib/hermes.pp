define nest::lib::hermes (
  String[1]            $profile                  = $title,
  String[1]            $display_name             = $title,
  Stdlib::Absolutepath $install_dir              = '/opt/hermes-agent',
  String[1]            $user                     = 'joy',
  String[1]            $gitlab_url               = 'https://gitlab.joyfullee.me',
  Any                  $gitlab_token             = undef,
  Boolean              $gitlab_enabled           = false,
  Any                  $openai_api_key           = undef,
  Any                  $tavily_api_key           = undef,
  Any                  $telegram_bot_token       = undef,
  Boolean              $telegram_enabled         = true,
  String[1]            $telegram_allowed         = '8756212310',
  String[1]            $telegram_home            = '8756212310',
  String[1]            $model_provider           = 'openai-codex',
  String[1]            $model_name               = 'gpt-5.5',
  String[1]            $model_base_url           = 'https://chatgpt.com/backend-api/codex',
  String[1]            $auxiliary_provider       = 'openai-codex',
  String[1]            $auxiliary_mini_model     = 'gpt-5.4-mini',
  Optional[String[1]]  $image_gen_provider       = undef,
  Optional[String[1]]  $image_gen_model          = undef,
  Integer[1]           $compression_timeout      = 120,
  Integer[1]           $web_extract_timeout      = 360,
  String[1]            $approval_mode            = 'manual',
  Boolean              $dashboard_enabled        = false,
  String[1]            $dashboard_bind_host      = '0.0.0.0',
  Stdlib::Port         $dashboard_port           = 9119,
  String[1]            $dashboard_public_url     = "https://${title}.eyrie",
  Optional[String[1]]  $dashboard_theme          = undef,
  Optional[String[1]]  $dashboard_oauth_client_id= undef,
  Optional[String[1]]  $dashboard_oauth_portal_url= undef,
  String[1]            $agent_request_kanban_board= 'agent-requests',
  Boolean              $kanban_dispatch_in_gateway= true,
  Boolean              $gateway_enabled          = true,
  Optional[String[1]]  $ssh_auth_sock            = undef,
  String[1]            $honcho_base_url          = 'https://honcho.eyrie',
  String[1]            $honcho_workspace         = 'hermes',
  String[1]            $honcho_user_peer         = 'joy',
  String[1]            $honcho_ai_peer           = $title,
  Optional[String[1]]  $soul_content             = undef,
  Optional[String[1]]  $skin_name                = undef,
  Optional[String[1]]  $skin_content             = undef,
  Optional[String[1]]  $skin_banner_hero_source  = undef,
  Array[String[1]]     $profile_toolsets         = ['hermes-cli', 'kanban'],
  Any                  $toolsets                 = undef,
  Any                  $telegram_toolsets        = undef,
  Boolean              $google_workspace_enabled = false,
  Boolean              $voice_auto_tts           = false,
  Boolean              $stt_enabled              = false,
  String[1]            $stt_provider             = 'openai',
  String[1]            $stt_model                = 'gpt-4o-mini-transcribe',
  String[1]            $tts_provider             = 'openai',
  String[1]            $tts_openai_model         = 'gpt-4o-mini-tts',
  String[1]            $tts_openai_voice         = 'alloy',
  Array[String[1]]     $extra_packages           = [],
) {
  $venv_dir                         = "${install_dir}/venv"
  $venv_python                      = "${venv_dir}/bin/python"
  $hermes_home_dir                  = "/home/${user}/.hermes"
  $profiles_dir                     = "${hermes_home_dir}/profiles"
  $profile_dir                      = "${profiles_dir}/${profile}"
  $hermes_env_path                  = "${profile_dir}/.env"
  $hermes_config_path               = "${profile_dir}/config.yaml"
  $hermes_managed_config_path       = "${profile_dir}/managed-config.yaml"
  $hermes_config_manager_path       = "${install_dir}/bin/manage-hermes-config"
  $hermes_honcho_config_path        = "${profile_dir}/honcho.json"
  $hermes_skins_dir                 = "${profile_dir}/skins"
  $systemd_user_dir                 = "/home/${user}/.config/systemd/user"
  $dashboard_oauth_client_id_value  = $dashboard_oauth_client_id ? {
    undef   => '',
    default => $dashboard_oauth_client_id,
  }
  $dashboard_oauth_portal_url_value = $dashboard_oauth_portal_url ? {
    undef   => '',
    default => $dashboard_oauth_portal_url,
  }
  $soul_seed                        = $soul_content ? {
    undef   => "# ${display_name}\n\nYou are ${display_name}, one of Joy's Hermes Agent profiles.\n",
    default => $soul_content,
  }
  $default_toolsets                  = [
    'agent_requests',
    'browser',
    'clarify',
    'code_execution',
    'computer_use',
    'cronjob',
    'delegation',
    'file',
    'image_gen',
    'kanban',
    'memory',
    'messaging',
    'session_search',
    'skills',
    'terminal',
    'todo',
    'tts',
    'vision',
    'web',
  ]
  $effective_toolsets                = pick($toolsets, $telegram_toolsets, $default_toolsets)
  $toolsets_yaml                     = $effective_toolsets.map |String[1] $toolset| {
    "          - ${toolset}"
  }.join("\n")
  $profile_toolsets_yaml             = $effective_toolsets.map |String[1] $toolset| {
    "        - ${toolset}"
  }.join("\n")
  $platform_toolsets_yaml            = [
    'cli',
    'cron',
    'telegram',
    'discord',
    'whatsapp',
    'slack',
    'signal',
    'homeassistant',
    'qqbot',
    'yuanbao',
    'teams',
    'google_chat',
  ].map |String[1] $platform| {
    "        ${platform}:\n${toolsets_yaml}"
  }.join("\n")

  ensure_resource('nest::lib::package', $extra_packages, {
    'ensure' => 'present',
  })

  if 'media-gfx/inkscape' in $extra_packages {
    nest::lib::package_use { 'hermes-inkscape-poppler':
      package => 'app-text/poppler',
      use     => ['cairo'],
    }

    nest::lib::package_use { 'hermes-inkscape-pillow':
      package => 'dev-python/pillow',
      use     => ['tiff', 'webp'],
    }

    nest::lib::package_use { 'hermes-inkscape-tiff':
      package => 'media-libs/tiff',
      use     => ['jpeg'],
    }

    Nest::Lib::Package_use['hermes-inkscape-poppler']
    -> Nest::Lib::Package_use['hermes-inkscape-pillow']
    -> Nest::Lib::Package_use['hermes-inkscape-tiff']
    -> Nest::Lib::Package['media-gfx/inkscape']
  }

  file { $profile_dir:
    ensure  => directory,
    mode    => '0700',
    owner   => $user,
    group   => $user,
    require => File[$profiles_dir],
  }

  file { "${profile_dir}/SOUL.md":
    ensure  => file,
    mode    => '0600',
    owner   => $user,
    group   => $user,
    content => $soul_seed,
    require => File[$profile_dir],
  }

  if $google_workspace_enabled {
    file { "${profile_dir}/skills":
      ensure  => directory,
      mode    => '0700',
      owner   => $user,
      group   => $user,
      require => File[$profile_dir],
    }

    file { "${profile_dir}/skills/productivity":
      ensure  => directory,
      mode    => '0700',
      owner   => $user,
      group   => $user,
      require => File["${profile_dir}/skills"],
    }

    file { "${profile_dir}/skills/productivity/google-workspace":
      ensure  => link,
      target  => "${install_dir}/src/skills/productivity/google-workspace",
      links   => manage,
      owner   => $user,
      group   => $user,
      require => [
        Exec['install_hermes_agent'],
        File["${profile_dir}/skills/productivity"],
      ],
    }
  }


  $gitlab_env_lines = $gitlab_token ? {
    undef   => [],
    default => $gitlab_enabled ? {
      true    => $gitlab_token =~ Sensitive[String[1]] ? {
        true    => ["GITLAB_URL=${gitlab_url}", "GITLAB_TOKEN=${gitlab_token.unwrap}"],
        default => ["GITLAB_URL=${gitlab_url}", "GITLAB_TOKEN=${gitlab_token}"],
      },
      default => [],
    },
  }

  $tavily_env_lines = $tavily_api_key ? {
    undef   => [],
    default => $tavily_api_key =~ Sensitive[String[1]] ? {
      true    => ["TAVILY_API_KEY=${tavily_api_key.unwrap}"],
      default => ["TAVILY_API_KEY=${tavily_api_key}"],
    },
  }

  $openai_env_lines = $openai_api_key ? {
    undef   => [],
    default => $openai_api_key =~ Sensitive[String[1]] ? {
      true    => ["OPENAI_API_KEY=${openai_api_key.unwrap}", "VOICE_TOOLS_OPENAI_KEY=${openai_api_key.unwrap}"],
      default => ["OPENAI_API_KEY=${openai_api_key}", "VOICE_TOOLS_OPENAI_KEY=${openai_api_key}"],
    },
  }

  $telegram_env_lines = $telegram_bot_token ? {
    undef   => [],
    default => $telegram_enabled ? {
      true    => $telegram_bot_token =~ Sensitive[String[1]] ? {
        true    => ["TELEGRAM_BOT_TOKEN=${telegram_bot_token.unwrap}", "TELEGRAM_ALLOWED_USERS=${telegram_allowed}", "TELEGRAM_HOME_CHANNEL=${telegram_home}"],
        default => ["TELEGRAM_BOT_TOKEN=${telegram_bot_token}", "TELEGRAM_ALLOWED_USERS=${telegram_allowed}", "TELEGRAM_HOME_CHANNEL=${telegram_home}"],
      },
      default => [],
    },
  }

  $agent_request_env_lines = [
    "AGENT_REQUEST_KANBAN_BOARD=${agent_request_kanban_board}",
    $voice_auto_tts ? {
      true    => ['AGENT_REQUEST_TELEGRAM_VOICE_NOTIFY=true'],
      default => [],
    },
  ].flatten
  $systemd_env_lines = [
    "HERMES_DASHBOARD_BIND_HOST=${dashboard_bind_host}",
    "HERMES_DASHBOARD_PORT=${dashboard_port}",
    "HERMES_DASHBOARD_PUBLIC_URL=${dashboard_public_url}",
    $ssh_auth_sock ? {
      undef   => [],
      default => ["SSH_AUTH_SOCK=${ssh_auth_sock}"],
    },
    $openai_env_lines,
    $agent_request_env_lines,
    '',
  ].flatten

  $image_gen_yaml = $image_gen_provider ? {
    undef   => '',
    default => $image_gen_model ? {
      undef   => @("YAML"),
        image_gen:
          provider: "${image_gen_provider}"
        | YAML
      default => @("YAML"),
        image_gen:
          provider: "${image_gen_provider}"
          model: "${image_gen_model}"
        | YAML
    },
  }
  $plugins_yaml = $image_gen_provider ? {
    undef   => '',
    default => @("YAML"),
      plugins:
        disabled: []
        enabled:
          - "image_gen/${image_gen_provider}"
      | YAML
  }
  $display_skin_yaml = $skin_name ? {
    undef   => '',
    default => "  skin: \"${skin_name}\"\n",
  }
  $skin_banner_hero_yaml = $skin_banner_hero_source ? {
    undef   => '',
    default => "banner_hero: |2\n${nest::ansi_to_rich($skin_banner_hero_source).split("\n").map |String $line| { "  ${line}" }.join("\n")}\n",
  }
  $dashboard_theme_yaml = $dashboard_theme ? {
    undef   => '',
    default => "  theme: \"${dashboard_theme}\"\n",
  }
  $effective_skin_content = $skin_content ? {
    undef   => undef,
    default => "${skin_content}${skin_banner_hero_yaml}",
  }
  $has_custom_skin = $skin_name != undef and $effective_skin_content != undef

  $env_content = [$gitlab_env_lines, $openai_env_lines, $tavily_env_lines, $telegram_env_lines, $agent_request_env_lines].flatten.join("\n")

  file { $hermes_env_path:
    ensure    => file,
    mode      => '0600',
    owner     => $user,
    group     => $user,
    content   => Sensitive([$env_content, ''].join("\n")),
    show_diff => false,
    require   => File[$profile_dir],
  }

  file { $hermes_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $user,
    group   => $user,
    content => "--- {}\n",
    replace => false,
    require => File[$profile_dir],
  }

  if $has_custom_skin {
    file { $hermes_skins_dir:
      ensure  => directory,
      mode    => '0700',
      owner   => $user,
      group   => $user,
      require => File[$profile_dir],
    }

    file { "${hermes_skins_dir}/${skin_name}.yaml":
      ensure    => file,
      mode      => '0600',
      owner     => $user,
      group     => $user,
      content   => $effective_skin_content,
      show_diff => false,
      require   => File[$hermes_skins_dir],
    }
  }

  file { "${profile_dir}/systemd.env":
    ensure    => file,
    mode      => '0600',
    owner     => $user,
    group     => $user,
    content   => Sensitive($systemd_env_lines.join("\n")),
    show_diff => false,
    require   => File[$profile_dir],
  }

  file { $hermes_managed_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $user,
    group   => $user,
    content => @("YAML"),
      ---
      toolsets:
${profile_toolsets_yaml}
      model:
        provider: "${model_provider}"
        default: "${model_name}"
        base_url: "${model_base_url}"
      web:
        backend: tavily
        search_backend: tavily
${image_gen_yaml}
${plugins_yaml}
      voice:
        auto_tts: ${voice_auto_tts}
      approvals:
        mode: "${approval_mode}"
      stt:
        enabled: ${stt_enabled}
        provider: "${stt_provider}"
        openai:
          model: "${stt_model}"
      tts:
        provider: "${tts_provider}"
        openai:
          model: "${tts_openai_model}"
          voice: "${tts_openai_voice}"

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
${platform_toolsets_yaml}
      display:
        tool_progress: all
        tool_progress_command: true
${display_skin_yaml}  platforms:
          telegram:
            tool_progress: all
            tool_preview_length: 500
      memory:
        provider: honcho
      kanban:
        dispatch_in_gateway: ${kanban_dispatch_in_gateway}
      dashboard:
        public_url: "${dashboard_public_url}"
${dashboard_theme_yaml}
        oauth:
          client_id: "${dashboard_oauth_client_id_value}"
          portal_url: "${dashboard_oauth_portal_url_value}"
      | YAML
    require => File[$profile_dir],
  }

  file { $hermes_honcho_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $user,
    group   => $user,
    content => @("JSON"),
      {
        "dialecticCadence": 2,
        "baseUrl": "${honcho_base_url}",
        "hosts": {
          "hermes.${profile}": {
            "workspace": "${honcho_workspace}",
            "peerName": "${honcho_user_peer}",
            "aiPeer": "${honcho_ai_peer}",
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
    require => File[$profile_dir],
  }

  $configure_require = $has_custom_skin ? {
    true    => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_honcho_deps'],
      File[$hermes_config_path],
      File[$hermes_config_manager_path],
      File[$hermes_managed_config_path],
      File[$hermes_honcho_config_path],
      File["${hermes_skins_dir}/${skin_name}.yaml"],
    ],
    default => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_honcho_deps'],
      File[$hermes_config_path],
      File[$hermes_config_manager_path],
      File[$hermes_managed_config_path],
      File[$hermes_honcho_config_path],
    ],
  }

  exec { "configure_hermes_managed_config_${profile}":
    command     => "${venv_python} ${hermes_config_manager_path} apply ${hermes_config_path} ${hermes_managed_config_path}",
    unless      => "${venv_python} ${hermes_config_manager_path} check ${hermes_config_path} ${hermes_managed_config_path}",
    user        => $user,
    environment => ["HOME=/home/${user}"],
    require     => $configure_require,
  }

  if $gateway_enabled {
    exec { "enable_hermes_gateway_${profile}":
      command => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-gateway@${profile}.service'",
      unless  => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-gateway@${profile}.service && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-gateway@${profile}.service'",
      user    => $user,
      require => [
        Exec['enable_hermes_gateway_linger'],
        File["${systemd_user_dir}/hermes-gateway@.service"],
        File["${profile_dir}/systemd.env"],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
    }

    exec { "restart_hermes_gateway_${profile}":
      command     => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user try-reload-or-restart hermes-gateway@${profile}.service'",
      refreshonly => true,
      user        => $user,
      subscribe   => [
        Exec['install_hermes_agent'],
        Exec['install_hermes_agent_request_broker'],
        File[$hermes_env_path],
        File["${profile_dir}/systemd.env"],
        File[$hermes_managed_config_path],
        File[$hermes_honcho_config_path],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
      require     => Exec["enable_hermes_gateway_${profile}"],
    }
  } else {
    exec { "disable_hermes_gateway_${profile}":
      command => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user disable --now hermes-gateway@${profile}.service || true'",
      unless  => "/bin/sh -c '! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-gateway@${profile}.service && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-gateway@${profile}.service'",
      user    => $user,
      require => File["${systemd_user_dir}/hermes-gateway@.service"],
    }
  }

  if $dashboard_enabled {
    exec { "enable_hermes_dashboard_${profile}":
      command => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-dashboard@${profile}.service'",
      unless  => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-dashboard@${profile}.service && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-dashboard@${profile}.service'",
      user    => $user,
      require => [
        Exec['enable_hermes_gateway_linger'],
        File["${systemd_user_dir}/hermes-dashboard@.service"],
        File["${profile_dir}/systemd.env"],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
    }

    exec { "restart_hermes_dashboard_${profile}":
      command     => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user try-reload-or-restart hermes-dashboard@${profile}.service'",
      refreshonly => true,
      user        => $user,
      subscribe   => [
        Exec['install_hermes_agent'],
        File["${profile_dir}/systemd.env"],
        File[$hermes_managed_config_path],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
      require     => Exec["enable_hermes_dashboard_${profile}"],
    }
  } else {
    exec { "disable_hermes_dashboard_${profile}":
      command => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user disable --now hermes-dashboard@${profile}.service || true'",
      unless  => "/bin/sh -c '! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-dashboard@${profile}.service && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-dashboard@${profile}.service'",
      user    => $user,
      require => File["${systemd_user_dir}/hermes-dashboard@.service"],
    }
  }
}
