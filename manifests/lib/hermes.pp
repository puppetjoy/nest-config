define nest::lib::hermes (
  String[1]            $profile                  = $title,
  String[1]            $display_name             = $title,
  Optional[String[1]]  $profile_icon             = undef,
  Stdlib::Absolutepath $install_dir              = '/opt/hermes-agent',
  Stdlib::Absolutepath $ca_bundle_file           = '/etc/ssl/certs/ca-certificates.crt',
  String[1]            $user                     = 'joy',
  String[1]            $gitlab_url               = 'https://gitlab.joyfullee.me',
  Any                  $gitlab_token             = undef,
  Boolean              $gitlab_enabled           = false,
  Any                  $tavily_api_key           = undef,
  Any                  $telegram_bot_token       = undef,
  Boolean              $telegram_enabled         = true,
  String[1]            $telegram_allowed         = '8756212310',
  String[1]            $telegram_home            = '8756212310',
  Optional[String[1]]  $telegram_bot_username    = undef,
  Optional[String[1]]  $telegram_bot_id          = undef,
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
  Boolean              $dashboard_profile_switcher= false,
  Optional[String[1]]  $dashboard_oauth_client_id= undef,
  Optional[String[1]]  $dashboard_oauth_portal_url= undef,
  String[1]            $agent_request_kanban_board= 'agent-requests',
  Boolean              $kanban_dispatch_in_gateway= true,
  Optional[String[1]]  $git_user_name            = undef,
  Optional[String[1]]  $git_user_email           = undef,
  Optional[String[1]]  $git_signing_key          = undef,
  Boolean              $git_commit_sign          = true,
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
  Boolean              $agent_directory_enabled  = true,
  String[1]            $agent_directory_board    = 'agent-directory',
  Integer[0]           $agent_directory_touch    = 3600,
  Boolean              $google_workspace_enabled = false,
  Boolean              $voice_auto_tts           = false,
  Boolean              $stt_enabled              = false,
  String[1]            $stt_provider             = 'voice-speech',
  Optional[String[1]]  $stt_voice_speech_endpoint= undef,
  String[1]            $stt_voice_speech_model   = 'whisper-large-v3-turbo',
  String[1]            $stt_voice_speech_language= 'en',
  String[1]            $stt_voice_speech_prompt  = 'Talon Star Honcho Eyrie KubeCM llama-qwen GitLab Puppet Kubernetes OpenVox ROCm kubectl owl voice-speech Kokoro',
  String[1]            $stt_voice_speech_temp    = '0.0',
  Boolean              $stt_voice_speech_prev_text= false,
  Integer[1]           $stt_voice_speech_timeout = 300,
  String[1]            $tts_provider             = 'voice-speech',
  Optional[String[1]]  $tts_voice_speech_endpoint= undef,
  String[1]            $tts_voice_speech_voice   = 'af_heart',
  String[1]            $tts_voice_speech_model   = 'kokoro',
  Integer[1]           $tts_voice_speech_timeout = 60,
  Any                  $ssh_private_key          = undef,
  Optional[String[1]]  $kubeconfig_path          = undef,
  Any                  $kubeconfig_content       = undef,
  Array[String[1]]     $extra_packages           = [],
  Boolean              $release_digest_enabled   = false,
) {
  $venv_dir                         = "${install_dir}/venv"
  $venv_python                      = "${venv_dir}/bin/python"
  $hermes_home_dir                  = "/home/${user}/.hermes"
  $profiles_dir                     = "${hermes_home_dir}/profiles"
  $profile_dir                      = "${profiles_dir}/${profile}"
  $ssh_dir                          = "${profile_dir}/.ssh"
  $ssh_private_key_path             = "${ssh_dir}/id_ed25519"
  $hermes_env_path                  = "${profile_dir}/.env"
  $hermes_config_path               = "${profile_dir}/config.yaml"
  $hermes_managed_config_path       = "${profile_dir}/managed-config.yaml"
  $hermes_config_manager_path       = "${install_dir}/bin/manage-hermes-config"
  $hermes_honcho_config_path        = "${profile_dir}/honcho.json"
  $hermes_skins_dir                 = "${profile_dir}/skins"
  $kubeconfig_dir                   = "${profile_dir}/kubeconfigs"
  $effective_kubeconfig_path        = $kubeconfig_path ? {
    undef   => "${kubeconfig_dir}/eyrie.conf",
    default => $kubeconfig_path,
  }
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
    undef   => fail("Hermes profile ${profile} must set soul_content from private Hiera"),
    default => $soul_content,
  }
  $agent_directory_freshness_notes  = "Puppet-managed ${display_name} lifecycle refresh"
  $default_toolsets                  = [
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
    'session_search',
    'shopping_browser',
    'skills',
    'terminal',
    'todo',
    'tts',
    'vision',
    'web',
  ]
  $effective_toolsets                = pick($toolsets, $telegram_toolsets, $default_toolsets)
  $platform_toolsets                 = [
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
  ].reduce({}) |Hash $memo, String[1] $platform| {
    $memo + { $platform => $effective_toolsets }
  }

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

  if $release_digest_enabled {
    file { "${profile_dir}/scripts":
      ensure  => directory,
      mode    => '0700',
      owner   => $user,
      group   => $user,
      require => File[$profile_dir],
    }

    file { "${profile_dir}/scripts/release_digest.py":
      ensure  => file,
      mode    => '0755',
      owner   => $user,
      group   => $user,
      source  => 'puppet:///modules/nest/app/hermes/release_digest.py',
      require => File["${profile_dir}/scripts"],
    }
  }

  if $ssh_private_key != undef {
    $effective_ssh_private_key = $ssh_private_key =~ Sensitive ? {
      true    => $ssh_private_key,
      default => Sensitive($ssh_private_key),
    }

    file { $ssh_dir:
      ensure  => directory,
      mode    => '0700',
      owner   => $user,
      group   => $user,
      require => File[$profile_dir],
    }

    file { $ssh_private_key_path:
      ensure    => file,
      mode      => '0600',
      owner     => $user,
      group     => $user,
      content   => $effective_ssh_private_key,
      show_diff => false,
      require   => File[$ssh_dir],
    }
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
  $kubeconfig_env_lines = $kubeconfig_path ? {
    undef   => $kubeconfig_content ? {
      undef   => [],
      default => ["KUBECONFIG=${effective_kubeconfig_path}"],
    },
    default => ["KUBECONFIG=${effective_kubeconfig_path}"],
  }
  $kubeconfig_subscribe = $kubeconfig_content ? {
    undef   => [],
    default => [File[$effective_kubeconfig_path]],
  }
  $ssh_env_lines = $ssh_private_key ? {
    undef   => [],
    default => [
      "HERMES_SSH_PRIVATE_KEY=${ssh_private_key_path}",
      "GIT_SSH_COMMAND=\"ssh -i ${ssh_private_key_path} -o IdentitiesOnly=yes -o ControlMaster=no -o ControlPath=none\"",
    ],
  }
  $effective_git_signing_key = $git_signing_key ? {
    undef   => $ssh_private_key ? {
      undef   => undef,
      default => $ssh_private_key_path,
    },
    default => $git_signing_key,
  }
  $git_ssh_command = $ssh_private_key ? {
    undef   => undef,
    default => "ssh -i ${ssh_private_key_path} -o IdentitiesOnly=yes -o ControlMaster=no -o ControlPath=none",
  }
  $git_config_signing_lines = $effective_git_signing_key ? {
    undef   => [],
    default => [
      'GIT_CONFIG_KEY_2=user.signingkey',
      "GIT_CONFIG_VALUE_2=${effective_git_signing_key}",
      'GIT_CONFIG_KEY_3=gpg.format',
      'GIT_CONFIG_VALUE_3=ssh',
      'GIT_CONFIG_KEY_4=commit.gpgsign',
      "GIT_CONFIG_VALUE_4=${git_commit_sign}",
    ],
  }
  $git_config_ssh_lines = $git_ssh_command ? {
    undef   => [],
    default => [
      'GIT_CONFIG_KEY_5=core.sshCommand',
      "GIT_CONFIG_VALUE_5=${git_ssh_command}",
    ],
  }
  $git_config_count = 2 + (length($git_config_signing_lines) / 2) + (length($git_config_ssh_lines) / 2)
  $git_env_lines = ($git_user_name and $git_user_email) ? {
    true    => [
      "GIT_AUTHOR_NAME=${git_user_name}",
      "GIT_AUTHOR_EMAIL=${git_user_email}",
      "GIT_COMMITTER_NAME=${git_user_name}",
      "GIT_COMMITTER_EMAIL=${git_user_email}",
      "AGENT_REQUEST_GIT_USER_NAME=${git_user_name}",
      "AGENT_REQUEST_GIT_USER_EMAIL=${git_user_email}",
      $effective_git_signing_key ? {
        undef   => [],
        default => [
          "AGENT_REQUEST_GIT_SIGNING_KEY=${effective_git_signing_key}",
          "AGENT_REQUEST_GIT_COMMIT_GPGSIGN=${git_commit_sign}",
        ],
      },
      $git_ssh_command ? {
        undef   => [],
        default => ["AGENT_REQUEST_GIT_SSH_COMMAND=${git_ssh_command}"],
      },
      "GIT_CONFIG_COUNT=${git_config_count}",
      'GIT_CONFIG_KEY_0=user.name',
      "GIT_CONFIG_VALUE_0=${git_user_name}",
      'GIT_CONFIG_KEY_1=user.email',
      "GIT_CONFIG_VALUE_1=${git_user_email}",
      $git_config_signing_lines,
      $git_config_ssh_lines,
    ].flatten,
    default => [],
  }
  $systemd_env_lines = [
    "HERMES_DASHBOARD_BIND_HOST=${dashboard_bind_host}",
    "HERMES_DASHBOARD_PORT=${dashboard_port}",
    "HERMES_DASHBOARD_PUBLIC_URL=${dashboard_public_url}",
    $ssh_auth_sock ? {
      undef   => [],
      default => ["SSH_AUTH_SOCK=${ssh_auth_sock}"],
    },
    $telegram_env_lines,
    $agent_request_env_lines,
    $ssh_env_lines,
    $git_env_lines,
    $kubeconfig_env_lines,
    "SSL_CERT_FILE=${ca_bundle_file}",
    "REQUESTS_CA_BUNDLE=${ca_bundle_file}",
    "CURL_CA_BUNDLE=${ca_bundle_file}",
    'SSL_CERT_DIR=/etc/ssl/certs',
    '',
  ].flatten

  $image_gen_config = $image_gen_provider ? {
    undef   => {},
    default => {
      'image_gen' => {
        'provider' => $image_gen_provider,
      } + ($image_gen_model ? {
        undef   => {},
        default => { 'model' => $image_gen_model },
      }),
    },
  }
  $plugins_config = $image_gen_provider ? {
    undef   => {},
    default => {
      'plugins' => {
        'disabled' => [],
        'enabled'  => ["image_gen/${image_gen_provider}"],
      },
    },
  }
  $display_skin_config = $skin_name ? {
    undef   => {},
    default => { 'skin' => $skin_name },
  }
  $skin_banner_hero_yaml = $skin_banner_hero_source ? {
    undef   => '',
    default => "banner_hero: |2\n${nest::ansi_to_rich($skin_banner_hero_source).split("\n").map |String $line| { "  ${line}" }.join("\n")}\n",
  }
  $dashboard_theme_config = $dashboard_theme ? {
    undef   => {},
    default => { 'theme' => $dashboard_theme },
  }
  $dashboard_profile_switcher_config = {
    'show_profile_switcher' => $dashboard_profile_switcher,
  }
  $agent_directory_profile_icon_config = $profile_icon ? {
    undef   => {},
    default => { 'profile_icon' => $profile_icon },
  }
  $telegram_bot_username_config = $telegram_bot_username ? {
    undef   => {},
    default => { 'expected_bot_username' => $telegram_bot_username },
  }
  $telegram_bot_id_config = $telegram_bot_id ? {
    undef   => {},
    default => { 'expected_bot_id' => $telegram_bot_id },
  }
  $telegram_config = $telegram_bot_username_config + $telegram_bot_id_config
  $stt_voice_speech_condition_arg = $stt_voice_speech_prev_text ? {
    true    => '--condition-on-previous-text',
    default => '',
  }
  $stt_voice_speech_provider_config = $stt_voice_speech_endpoint ? {
    undef   => {},
    default => {
      'providers' => {
        'voice-speech' => {
          'type'     => 'command',
          'command'  => "${install_dir}/bin/hermes-voice-speech-stt --endpoint ${stt_voice_speech_endpoint} --input {input_path} --output {output_path} --model {model} --language {language} --format {format} --temperature ${stt_voice_speech_temp} --timeout ${stt_voice_speech_timeout} --initial-prompt '${stt_voice_speech_prompt}' ${stt_voice_speech_condition_arg}",
          'format'   => 'txt',
          'language' => $stt_voice_speech_language,
          'model'    => $stt_voice_speech_model,
          'timeout'  => $stt_voice_speech_timeout,
        },
      },
    },
  }
  $tts_voice_speech_providers = $tts_voice_speech_endpoint ? {
    undef   => {},
    default => {
      'voice-speech' => {
        'type'             => 'command',
        'command'          => "${install_dir}/bin/hermes-voice-speech-tts --endpoint ${tts_voice_speech_endpoint} --text-file {input_path} --output {output_path} --voice {voice} --model {model} --format {format} --speed {speed}",
        'output_format'    => 'wav',
        'voice'            => $tts_voice_speech_voice,
        'model'            => $tts_voice_speech_model,
        'timeout'          => $tts_voice_speech_timeout,
        'max_text_length'  => 4096,
        'voice_compatible' => true,
      },
    },
  }
  $effective_skin_content = $skin_content ? {
    undef   => undef,
    default => "${skin_content}${skin_banner_hero_yaml}",
  }
  $has_custom_skin = $skin_name != undef and $effective_skin_content != undef

  $managed_config = {
    'toolsets'         => $effective_toolsets,
    'model'            => {
      'provider' => $model_provider,
      'default'  => $model_name,
      'base_url' => $model_base_url,
    },
    'web'              => {
      'backend'        => 'tavily',
      'search_backend' => 'tavily',
    },
    'voice'            => {
      'auto_tts' => $voice_auto_tts,
    },
    'approvals'        => {
      'mode' => $approval_mode,
    },
    'stt'              => {
      'enabled'  => $stt_enabled,
      'provider' => $stt_provider,
      'codex'    => {
        '__managed_absent__' => true,
      },
      'openai'   => {
        '__managed_absent__' => true,
      },
    } + $stt_voice_speech_provider_config,
    'tts'              => ({
      'provider'  => $tts_provider,
      'openai'    => {
        '__managed_absent__' => true,
      },
      'providers' => $tts_voice_speech_providers,
    }),
    'auxiliary'        => {
      'compression' => {
        'provider' => $auxiliary_provider,
        'model'    => $auxiliary_mini_model,
        'timeout'  => $compression_timeout,
      },
      'web_extract' => {
        'provider' => $auxiliary_provider,
        'model'    => $auxiliary_mini_model,
        'timeout'  => $web_extract_timeout,
      },
    },
    'platform_toolsets' => $platform_toolsets,
    'telegram'          => $telegram_config,
    'display'           => {
      'tool_progress'         => 'all',
      'tool_progress_command' => true,
      'platforms'             => {
        'telegram' => {
          'tool_progress' => 'all',
        },
      },
    } + $display_skin_config,
    'memory'           => {
      'provider' => 'honcho',
    },
    'agent_directory'  => {
      'enabled'                => $agent_directory_enabled,
      'board'                  => $agent_directory_board,
      'touch_interval_seconds' => $agent_directory_touch,
      'profile_name'           => $profile,
      'profile'                => {
        'display_name'    => $display_name,
        'freshness_notes' => $agent_directory_freshness_notes,
      } + $agent_directory_profile_icon_config,
    },
    'kanban'           => {
      'dispatch_in_gateway' => $kanban_dispatch_in_gateway,
    },
    'dashboard'        => {
      'public_url' => $dashboard_public_url,
      'oauth'      => {
        'client_id'  => $dashboard_oauth_client_id_value,
        'portal_url' => $dashboard_oauth_portal_url_value,
      },
    } + $dashboard_theme_config + $dashboard_profile_switcher_config,
  } + $image_gen_config + $plugins_config

  $env_content = [$gitlab_env_lines, $tavily_env_lines, $telegram_env_lines, $agent_request_env_lines, $ssh_env_lines, $kubeconfig_env_lines].flatten.join("\n")

  if $kubeconfig_content != undef {
    $effective_kubeconfig_content = $kubeconfig_content =~ Sensitive ? {
      true    => $kubeconfig_content,
      default => Sensitive($kubeconfig_content),
    }

    file { $kubeconfig_dir:
      ensure  => directory,
      mode    => '0700',
      owner   => $user,
      group   => $user,
      require => File[$profile_dir],
    }

    file { $effective_kubeconfig_path:
      ensure    => file,
      mode      => '0600',
      owner     => $user,
      group     => $user,
      content   => $effective_kubeconfig_content,
      show_diff => false,
      require   => File[$kubeconfig_dir],
    }
  }

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
    content => $managed_config.stdlib::to_yaml,
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
      Python::Pip['hermes-agent-honcho-deps'],
      File[$hermes_config_path],
      File[$hermes_config_manager_path],
      File[$hermes_managed_config_path],
      File[$hermes_honcho_config_path],
      File["${hermes_skins_dir}/${skin_name}.yaml"],
    ],
    default => [
      Exec['install_hermes_agent'],
      Python::Pip['hermes-agent-honcho-deps'],
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
    systemd::user_service { "hermes-gateway-${profile}":
      ensure  => running,
      enable  => true,
      unit    => "hermes-gateway@${profile}.service",
      user    => $user,
      require => [
        Loginctl_user[$user],
        Systemd::Manage_unit['hermes-gateway@.service'],
        File["${profile_dir}/systemd.env"],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
    }

    exec { "restart_hermes_gateway_${profile}":
      command     => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) ${install_dir}/bin/hermes-systemd-user-refresh hermes-gateway@${profile}.service 300'",
      refreshonly => true,
      user        => $user,
      subscribe   => [
        Exec['install_hermes_agent'],
        Exec['install_hermes_agent_request_broker'],
        Exec['share_hermes_codex_auth'],
        File[$hermes_env_path],
        File["${profile_dir}/systemd.env"],
        $kubeconfig_subscribe,
        File[$hermes_managed_config_path],
        File[$hermes_honcho_config_path],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
      require     => [
        Systemd::User_service["hermes-gateway-${profile}"],
        File["${install_dir}/bin/hermes-systemd-user-refresh"],
      ],
    }
  } else {
    systemd::user_service { "hermes-gateway-${profile}":
      ensure  => stopped,
      enable  => false,
      unit    => "hermes-gateway@${profile}.service",
      user    => $user,
      require => Systemd::Manage_unit['hermes-gateway@.service'],
    }
  }

  if $dashboard_enabled {
    systemd::user_service { "hermes-dashboard-${profile}":
      ensure  => running,
      enable  => true,
      unit    => "hermes-dashboard@${profile}.service",
      user    => $user,
      require => [
        Loginctl_user[$user],
        Systemd::Manage_unit['hermes-dashboard@.service'],
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
        Exec['share_hermes_codex_auth'],
        File["${profile_dir}/systemd.env"],
        $kubeconfig_subscribe,
        File[$hermes_managed_config_path],
        Exec["configure_hermes_managed_config_${profile}"],
      ],
      require     => Systemd::User_service["hermes-dashboard-${profile}"],
    }
  } else {
    systemd::user_service { "hermes-dashboard-${profile}":
      ensure  => stopped,
      enable  => false,
      unit    => "hermes-dashboard@${profile}.service",
      user    => $user,
      require => Systemd::Manage_unit['hermes-dashboard@.service'],
    }
  }
}
