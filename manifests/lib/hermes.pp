define nest::lib::hermes (
  String[1]            $profile                  = $title,
  String[1]            $display_name             = $title,
  Stdlib::Absolutepath $install_dir              = '/opt/hermes-agent',
  String[1]            $user                     = 'joy',
  String[1]            $gitlab_url               = 'https://gitlab.joyfullee.me',
  Any                  $gitlab_token             = undef,
  Boolean              $gitlab_enabled           = false,
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
  Integer[1]           $compression_timeout      = 120,
  Integer[1]           $web_extract_timeout      = 360,
  Boolean              $dashboard_enabled        = false,
  String[1]            $dashboard_bind_host      = '0.0.0.0',
  Stdlib::Port         $dashboard_port           = 9119,
  String[1]            $dashboard_public_url     = "https://${title}.eyrie",
  Optional[String[1]]  $dashboard_oauth_client_id= undef,
  Optional[String[1]]  $dashboard_oauth_portal_url= undef,
  Boolean              $gateway_enabled          = true,
  String[1]            $honcho_base_url          = 'https://honcho.eyrie',
  String[1]            $honcho_workspace         = 'hermes',
  String[1]            $honcho_user_peer         = 'joy',
  String[1]            $honcho_ai_peer           = $title,
  Optional[String[1]]  $soul_content             = undef,
  Boolean              $clone_from_default       = false,
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

  file { $profile_dir:
    ensure  => directory,
    mode    => '0700',
    owner   => $user,
    group   => $user,
    require => File[$profiles_dir],
  }

  if $clone_from_default {
    exec { "bootstrap_hermes_profile_${profile}":
      command => @("COMMAND"/L),
        /bin/sh -c '
        set -eu
        cd ${hermes_home_dir}
        for path in sessions memories skills cron logs; do
          if [ -e "${path}" ] && [ ! -e "profiles/${profile}/${path}" ]; then
            cp -a "${path}" "profiles/${profile}/${path}"
          fi
        done
        for path in .env SOUL.md auth.json; do
          if [ -e "${path}" ] && [ ! -e "profiles/${profile}/${path}" ]; then
            cp -a "${path}" "profiles/${profile}/${path}"
          fi
        done
        touch "profiles/${profile}/.profile-bootstrap-complete"
        '
        | COMMAND
      creates => "${profile_dir}/.profile-bootstrap-complete",
      user    => $user,
      require => File[$profile_dir],
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

  $env_content = [$gitlab_env_lines, $tavily_env_lines, $telegram_env_lines].flatten.join("\n")

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

  file { $hermes_managed_config_path:
    ensure  => file,
    mode    => '0600',
    owner   => $user,
    group   => $user,
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
          "hermes": {
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

  exec { "configure_hermes_managed_config_${profile}":
    command     => "${venv_python} ${hermes_config_manager_path} apply ${hermes_config_path} ${hermes_managed_config_path}",
    unless      => "${venv_python} ${hermes_config_manager_path} check ${hermes_config_path} ${hermes_managed_config_path}",
    user        => $user,
    environment => ["HOME=/home/${user}"],
    require     => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_honcho_deps'],
      File[$hermes_config_path],
      File[$hermes_config_manager_path],
      File[$hermes_managed_config_path],
      File[$hermes_honcho_config_path],
    ],
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
  } else {
    exec { "disable_hermes_dashboard_${profile}":
      command => "/bin/sh -c 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user disable --now hermes-dashboard@${profile}.service || true'",
      unless  => "/bin/sh -c '! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-dashboard@${profile}.service && ! XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-dashboard@${profile}.service'",
      user    => $user,
      require => File["${systemd_user_dir}/hermes-dashboard@.service"],
    }
  }
}
