class nest::app::hermes (
  Optional[String[1]]            $version          = undef,
  Stdlib::Absolutepath           $install_dir      = '/opt/hermes-agent',
  Boolean                        $install_from_git = false,
  String[1]                      $git_url          = 'https://github.com/NousResearch/hermes-agent.git',
  String[1]                      $git_ref          = 'main',
  String[1]                      $gitlab_url       = 'https://gitlab.joyfullee.me',
  Optional[Sensitive[String[1]]] $gitlab_token     = undef,
  Optional[Sensitive[String[1]]] $tavily_api_key   = undef,
  Optional[Sensitive[String[1]]] $honcho_api_key   = undef,
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

      if $install_from_git {
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
      } else {
        $package_spec = $version ? {
          undef   => 'hermes-agent',
          default => "hermes-agent==${version}",
        }

        $install_unless = $version ? {
          undef   => "${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\"",
          default => "${venv_python} -c \"import importlib.metadata as m; raise SystemExit(0 if m.version('hermes-agent') == '${version}' else 1)\"",
        }

        exec { 'install_hermes_agent':
          command     => "${venv_pip} install ${package_spec}",
          unless      => $install_unless,
          environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
          require     => Exec['create_hermes_venv'],
        }
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

      if $honcho_api_key {
        exec { 'install_hermes_honcho_deps':
          command     => "${venv_pip} install 'honcho-ai>=2.0.1'",
          unless      => "${venv_python} -c \"import honcho\"",
          environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
          require     => Exec['install_hermes_agent'],
        }
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

        exec { 'configure_hermes_tavily_search_backend':
          command     => "${venv_dir}/bin/hermes config set web.backend tavily && ${venv_dir}/bin/hermes config set web.search_backend tavily",
          unless      => "${venv_python} -c \"import pathlib, sys, yaml; p = pathlib.Path('${hermes_config_path}'); cfg = yaml.safe_load(p.read_text()) if p.exists() else {}; web = (cfg or {}).get('web', {}); sys.exit(0 if web.get('backend') == 'tavily' and web.get('search_backend') == 'tavily' else 1)\"",
          user        => $nest::user,
          environment => ["HOME=/home/${nest::user}"],
          require     => Exec['install_hermes_agent'],
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

      exec { 'configure_hermes_web_extract_auxiliary':
        command     => @("SH"),
          ${venv_dir}/bin/hermes config set auxiliary.web_extract.provider openai-codex && \
            ${venv_dir}/bin/hermes config set auxiliary.web_extract.model gpt-5.4-mini
          | SH
        unless      => @("SH"),
          ${venv_python} - <<'PY'
          import pathlib
          import sys
          import yaml

          p = pathlib.Path('${hermes_config_path}')
          cfg = yaml.safe_load(p.read_text()) if p.exists() else {}
          auxiliary = (cfg or {}).get('auxiliary', {}) or {}
          web_extract = auxiliary.get('web_extract', {}) or {}
          sys.exit(0 if web_extract.get('provider') == 'openai-codex'
                   and web_extract.get('model') == 'gpt-5.4-mini' else 1)
          PY
          | SH
        user        => $nest::user,
        environment => ["HOME=/home/${nest::user}"],
        require     => Exec['install_hermes_agent'],
      }

      if $honcho_api_key {
        file_line { 'hermes-env-honcho-api-key':
          path    => $hermes_env_path,
          line    => Sensitive("HONCHO_API_KEY=${honcho_api_key.unwrap}"),
          match   => '^HONCHO_API_KEY=',
          require => File[$hermes_env_path],
        }

        file { $hermes_honcho_config_path:
          ensure  => file,
          mode    => '0600',
          owner   => $nest::user,
          group   => $nest::user,
          content => @("JSON"),
            {
              "dialecticCadence": 2,
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

        exec { 'configure_hermes_honcho_memory_provider':
          command     => "${venv_dir}/bin/hermes config set memory.provider honcho",
          unless      => "${venv_python} -c \"import pathlib, sys, yaml; p = pathlib.Path('${hermes_config_path}'); cfg = yaml.safe_load(p.read_text()) if p.exists() else {}; memory = (cfg or {}).get('memory', {}); sys.exit(0 if memory.get('provider') == 'honcho' else 1)\"",
          user        => $nest::user,
          environment => ["HOME=/home/${nest::user}"],
          require     => [
            Exec['install_hermes_agent'],
            Exec['install_hermes_honcho_deps'],
            File[$hermes_honcho_config_path],
          ],
        }
      } else {
        file_line { 'hermes-env-honcho-api-key':
          ensure            => absent,
          path              => $hermes_env_path,
          match             => '^HONCHO_API_KEY=',
          match_for_absence => true,
          multiple          => true,
          require           => File[$hermes_env_path],
        }
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

      File["${systemd_user_dir}/${hermes_environment_unit}"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/10-shell-environment.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      File["${hermes_gateway_dropin_dir}/10-ssh-agent.conf"]
      ~>
      Exec['hermes-gateway-systemd-user-daemon-reload']

      exec { 'hermes-gateway-systemd-user-daemon-reload':
        command     => '/bin/sh -c "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload"',
        user        => $nest::user,
        refreshonly => true,
      }
    }
  }
}
