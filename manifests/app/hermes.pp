class nest::app::hermes (
  Stdlib::Absolutepath           $install_dir          = '/opt/hermes-agent',
  String[1]                      $git_url              = 'https://github.com/NousResearch/hermes-agent.git',
  String[1]                      $git_ref              = 'main',
  String[1]                      $gitlab_url           = 'https://gitlab.joyfullee.me',
  Optional[Sensitive[String[1]]] $gitlab_token         = undef,
  Optional[Sensitive[String[1]]] $tavily_api_key       = undef,
  Optional[Sensitive[String[1]]] $telegram_bot_token   = undef,
  String[1]                      $telegram_allowed     = '8756212310',
  String[1]                      $telegram_home        = '8756212310',
  String[1]                      $model_provider       = 'openai-codex',
  String[1]                      $model_name           = 'gpt-5.5',
  String[1]                      $model_base_url       = 'https://chatgpt.com/backend-api/codex',
  String[1]                      $auxiliary_provider   = 'openai-codex',
  String[1]                      $auxiliary_mini_model = 'gpt-5.4-mini',
  Integer[1]                     $compression_timeout  = 120,
  Integer[1]                     $web_extract_timeout  = 360,
) {
  case $facts['os']['family'] {
    'Gentoo': {
      $venv_dir                   = "${install_dir}/venv"
      $venv_python                = "${venv_dir}/bin/python"
      $venv_pip                   = "${venv_dir}/bin/pip"
      $source_dir                 = "${install_dir}/src"
      $git_revision_file          = "${install_dir}/.installed-git-revision"
      $hermes_config_dir          = "/home/${nest::user}/.config/hermes"
      $hermes_home_dir            = "/home/${nest::user}/.hermes"
      $hermes_env_path            = "${hermes_home_dir}/.env"
      $hermes_config_path         = "${hermes_home_dir}/config.yaml"
      $hermes_honcho_config_path  = "${hermes_home_dir}/honcho.json"
      $systemd_user_dir           = "/home/${nest::user}/.config/systemd/user"
      $hermes_gateway_dropin_dir  = "${systemd_user_dir}/hermes-gateway.service.d"
      $hermes_environment_unit    = 'hermes-environment.service'

      nest::lib::package { 'dev-python/virtualenv':
        ensure => present,
      }

      ensure_resource('nest::lib::package', 'sys-apps/ripgrep', {
        'ensure' => 'present',
      })

      file { $install_dir:
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }

      exec { 'create_hermes_venv':
        command => "/usr/bin/python3 -m virtualenv ${venv_dir}",
        creates => $venv_python,
        require => [
          File[$install_dir],
          Nest::Lib::Package['dev-python/virtualenv'],
        ],
      }

      include 'nest::base::git'

      vcsrepo { $source_dir:
        ensure   => latest,
        provider => git,
        source   => $git_url,
        revision => $git_ref,
        require  => [
          File[$install_dir],
          Class['nest::base::git'],
        ],
      }

      exec { 'install_hermes_agent':
        command     => "${venv_pip} install --upgrade --force-reinstall ${source_dir} && git -C ${source_dir} rev-parse HEAD > ${git_revision_file}",
        unless      => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\"",
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
        path        => ['/bin', '/usr/bin'],
        require     => [
          Exec['create_hermes_venv'],
          Vcsrepo[$source_dir],
        ],
      }

      file { '/usr/local/bin/hermes':
        ensure  => link,
        target  => "${venv_dir}/bin/hermes",
        require => Exec['install_hermes_agent'],
      }

      exec { 'install_hermes_telegram_deps':
        command     => "${venv_pip} install 'python-telegram-bot[webhooks]==22.6'",
        unless      => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('python-telegram-bot') == '22.6' else 1)\"",
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
        require     => Exec['install_hermes_agent'],
      }

      exec { 'install_hermes_honcho_deps':
        command     => "${venv_pip} install 'honcho-ai>=2.0.1'",
        unless      => "${venv_python} -c \"import honcho\"",
        environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
        require     => Exec['install_hermes_agent'],
      }

      nest::lib::package { 'media-video/ffmpeg':
        ensure => present,
      }

      if $facts['profile']['architecture'] == 'amd64' {
        include 'nodejs'

        nest::lib::package_use { 'media-libs/freetype':
          use => ['harfbuzz'],
        }

        nest::lib::package { 'www-client/google-chrome':
          ensure  => present,
          require => Nest::Lib::Package_use['media-libs/freetype'],
        }

        file { '/usr/local/bin/google-chrome':
          ensure  => link,
          target  => '/usr/bin/google-chrome-stable',
          require => Nest::Lib::Package['www-client/google-chrome'],
        }

        exec { 'install_hermes_agent_browser':
          command     => "${nodejs::npm_path} install --global agent-browser@latest",
          unless      => "${nodejs::npm_path} list --global agent-browser --depth=0 >/dev/null 2>&1 && ${nodejs::npm_path} outdated --global agent-browser --depth=0 >/dev/null 2>&1",
          environment => ['HOME=/root'],
          require     => Class['nodejs'],
        }
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

      exec { 'configure_hermes_managed_config':
        command     => @("SH"),
          ${venv_python} - <<'PY'
          import pathlib
          import yaml

          p = pathlib.Path('${hermes_config_path}')
          cfg = yaml.safe_load(p.read_text()) if p.exists() else {}
          if not isinstance(cfg, dict):
              cfg = {}

          managed = {
              'model': {
                  'provider': '${model_provider}',
                  'default': '${model_name}',
                  'base_url': '${model_base_url}',
              },
              'web': {
                  'backend': 'tavily',
                  'search_backend': 'tavily',
              },
              'auxiliary': {
                  'compression': {
                      'provider': '${auxiliary_provider}',
                      'model': '${auxiliary_mini_model}',
                      'timeout': ${compression_timeout},
                  },
                  'web_extract': {
                      'provider': '${auxiliary_provider}',
                      'model': '${auxiliary_mini_model}',
                      'timeout': ${web_extract_timeout},
                  },
              },
              'platform_toolsets': {
                  'telegram': [
                      'browser', 'clarify', 'code_execution', 'computer_use', 'cronjob',
                      'delegation', 'file', 'image_gen', 'memory', 'messaging',
                      'session_search', 'skills', 'terminal', 'todo', 'tts', 'vision',
                      'web',
                  ],
              },
              'display': {
                  'tool_progress': 'all',
                  'tool_progress_command': True,
                  'platforms': {
                      'telegram': {
                          'tool_progress': 'all',
                          'tool_preview_length': 500,
                      },
                  },
              },
              'memory': {
                  'provider': 'honcho',
              },
          }

          def merge(dst, src):
              for key, value in src.items():
                  if isinstance(value, dict):
                      current = dst.get(key)
                      if not isinstance(current, dict):
                          current = {}
                          dst[key] = current
                      merge(current, value)
                  else:
                      dst[key] = value

          merge(cfg, managed)
          p.parent.mkdir(parents=True, exist_ok=True)
          p.write_text(yaml.safe_dump(cfg, sort_keys=True))
          PY
          | SH
        unless      => @("SH"),
          ${venv_python} - <<'PY'
          import pathlib
          import sys
          import yaml

          p = pathlib.Path('${hermes_config_path}')
          cfg = yaml.safe_load(p.read_text()) if p.exists() else {}
          if not isinstance(cfg, dict):
              cfg = {}

          expected = {
              ('model', 'provider'): '${model_provider}',
              ('model', 'default'): '${model_name}',
              ('model', 'base_url'): '${model_base_url}',
              ('web', 'backend'): 'tavily',
              ('web', 'search_backend'): 'tavily',
              ('auxiliary', 'compression', 'provider'): '${auxiliary_provider}',
              ('auxiliary', 'compression', 'model'): '${auxiliary_mini_model}',
              ('auxiliary', 'compression', 'timeout'): ${compression_timeout},
              ('auxiliary', 'web_extract', 'provider'): '${auxiliary_provider}',
              ('auxiliary', 'web_extract', 'model'): '${auxiliary_mini_model}',
              ('auxiliary', 'web_extract', 'timeout'): ${web_extract_timeout},
              ('display', 'tool_progress'): 'all',
              ('display', 'tool_progress_command'): True,
              ('display', 'platforms', 'telegram', 'tool_progress'): 'all',
              ('display', 'platforms', 'telegram', 'tool_preview_length'): 500,
              ('memory', 'provider'): 'honcho',
          }

          def get(path):
              cur = cfg
              for key in path:
                  if not isinstance(cur, dict):
                      return None
                  cur = cur.get(key)
              return cur

          toolsets = (((cfg.get('platform_toolsets') or {}).get('telegram')) or [])
          required_tools = {
              'browser', 'clarify', 'code_execution', 'computer_use', 'cronjob',
              'delegation', 'file', 'image_gen', 'memory', 'messaging',
              'session_search', 'skills', 'terminal', 'todo', 'tts', 'vision', 'web',
          }
          ok = all(get(path) == value for path, value in expected.items())
          ok = ok and required_tools.issubset(set(toolsets))
          sys.exit(0 if ok else 1)
          PY
          | SH
        user        => $nest::user,
        environment => ["HOME=/home/${nest::user}"],
        require     => [
          Exec['install_hermes_agent'],
          Exec['install_hermes_honcho_deps'],
          File[$hermes_config_path],
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

      file { $systemd_user_dir:
        ensure => directory,
        mode   => '0755',
        owner  => $nest::user,
        group  => $nest::user,
      }
      ->
      file { "${systemd_user_dir}/${hermes_environment_unit}":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => @("UNIT"),
          [Unit]
          Description=Import shell environment for Hermes Agent Gateway

          [Service]
          Type=oneshot
          ExecStart=/home/${nest::user}/bin/reset-systemd-environment
          | UNIT
      }


      file { "${systemd_user_dir}/hermes-gateway.service":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => @("UNIT"),
          [Unit]
          Description=Hermes Agent Gateway - Messaging Platform Integration
          After=network-online.target
          Wants=network-online.target
          StartLimitIntervalSec=0

          [Service]
          Type=simple
          ExecStart=${venv_python} -m hermes_cli.main gateway run --replace
          WorkingDirectory=/home/${nest::user}
          Environment="PATH=${venv_dir}/bin:/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
          Environment="VIRTUAL_ENV=${venv_dir}"
          Environment="HERMES_HOME=${hermes_home_dir}"
          Restart=always
          RestartSec=5
          RestartMaxDelaySec=300
          RestartSteps=5
          RestartForceExitStatus=75
          KillMode=mixed
          KillSignal=SIGTERM
          TimeoutStopSec=210
          StandardOutput=journal
          StandardError=journal

          [Install]
          WantedBy=default.target
          | UNIT
        require => Exec['install_hermes_agent'],
      }

      file { $hermes_gateway_dropin_dir:
        ensure => directory,
        mode   => '0755',
        owner  => $nest::user,
        group  => $nest::user,
      }
      ->
      file { "${hermes_gateway_dropin_dir}/10-shell-environment.conf":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => "[Unit]\nRequires=${hermes_environment_unit}\nAfter=${hermes_environment_unit}\n",
      }
      ->
      file { "${hermes_gateway_dropin_dir}/10-ssh-agent.conf":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => "[Service]\nEnvironment=SSH_AUTH_SOCK=%t/ssh-agent.socket\n",
      }
      ->
      file { "${hermes_gateway_dropin_dir}/20-system-cert-trust.conf":
        ensure  => file,
        mode    => '0644',
        owner   => $nest::user,
        group   => $nest::user,
        content => "[Service]\nEnvironment=SSL_CERT_FILE=\nEnvironment=SSL_CERT_DIR=/etc/ssl/certs\n",
      }

      File["${systemd_user_dir}/${hermes_environment_unit}"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']


      File["${systemd_user_dir}/hermes-gateway.service"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/20-system-cert-trust.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      exec { 'hermes-gateway-systemd-user-daemon-reload':
        command     => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"',
        user        => $nest::user,
        refreshonly => true,
      }


      exec { 'enable_hermes_gateway_linger':
        command => "/usr/bin/loginctl enable-linger ${nest::user}",
        unless  => "/usr/bin/loginctl show-user ${nest::user} -p Linger --value | /bin/grep -qx yes",
      }

      exec { 'enable_hermes_gateway_service':
        command => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user enable --now hermes-gateway.service"',
        unless  => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-enabled --quiet hermes-gateway.service && XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active --quiet hermes-gateway.service"',
        user    => $nest::user,
        require => [
          Exec['enable_hermes_gateway_linger'],
          File["${systemd_user_dir}/hermes-gateway.service"],
          File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"],
          File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"],
          File["${hermes_gateway_dropin_dir}/20-system-cert-trust.conf"],
        ],
      }
    }
  }
}
