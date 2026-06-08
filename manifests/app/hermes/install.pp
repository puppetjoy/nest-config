class nest::app::hermes::install {
  $install_dir       = $nest::app::hermes::install_dir
  $git_url           = $nest::app::hermes::git_url
  $git_ref           = $nest::app::hermes::git_ref
  $git_commit        = $nest::app::hermes::git_commit
  $git_revision      = pick($git_commit, $git_ref)
  $venv_dir          = "${install_dir}/venv"
  $venv_python       = "${venv_dir}/bin/python"
  $venv_pip          = "${venv_dir}/bin/pip"
  $source_dir        = "${install_dir}/src"
  $broker_git_url    = $nest::app::hermes::broker_git_url
  $broker_git_ref    = $nest::app::hermes::broker_git_ref
  $broker_source_dir = "${install_dir}/agent-request-broker"
  $broker_git_identity = "/home/${nest::user}/.ssh/id_ed25519"
  $gws_dir           = '/opt/google-workspace-cli'
  $git_revision_file        = "${install_dir}/.installed-git-revision"
  $broker_git_revision_file = "${install_dir}/.installed-agent-request-broker-revision"
  $tui_revision_file        = "${install_dir}/.installed-tui-revision"
  $web_revision_file        = "${install_dir}/.installed-web-revision"

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

  exec { 'set_hermes_source_remote':
    command => "/usr/sbin/git -C ${source_dir} remote set-url origin ${git_url}",
    onlyif  => "/bin/sh -c 'test -d ${source_dir}/.git && test \$(/usr/sbin/git -C ${source_dir} remote get-url origin) != ${git_url}'",
    require => [
      File[$install_dir],
      Class['nest::base::git'],
    ],
  }

  vcsrepo { $source_dir:
    ensure   => latest,
    provider => git,
    source   => $git_url,
    revision => $git_revision,
    require  => [
      File[$install_dir],
      Class['nest::base::git'],
      Exec['set_hermes_source_remote'],
    ],
  }

  if $git_commit {
    exec { 'verify_hermes_source_ref_pin':
      command => "/bin/sh -c 'echo Hermes source ref ${git_ref} no longer resolves to pinned commit ${git_commit} >&2; exit 1'",
      unless  => "/bin/sh -c 'resolved=$(/usr/sbin/git -C ${source_dir} rev-parse --verify --quiet ${git_ref}^{commit} || /usr/sbin/git -C ${source_dir} rev-parse --verify --quiet origin/${git_ref}^{commit}); test \"\$resolved\" = ${git_commit}'",
      require => Vcsrepo[$source_dir],
    }
  }

  exec { 'set_hermes_agent_request_broker_remote':
    command => "/usr/sbin/git -C ${broker_source_dir} remote set-url origin ${broker_git_url}",
    onlyif  => "/bin/sh -c 'test -d ${broker_source_dir}/.git && test \$(/usr/sbin/git -C ${broker_source_dir} remote get-url origin) != ${broker_git_url}'",
    require => [
      File[$install_dir],
      Class['nest::base::git'],
    ],
  }

  vcsrepo { $broker_source_dir:
    ensure   => latest,
    provider => git,
    source   => $broker_git_url,
    revision => $broker_git_ref,
    identity => $broker_git_identity,
    require  => [
      File[$install_dir],
      Class['nest::base::git'],
      Exec['set_hermes_agent_request_broker_remote'],
    ],
  }

  file { [
    "${install_dir}/kanban-cross-board-phantom-references.patch",
    "${install_dir}/kanban-legacy-prose-diagnostic-reclassification.patch",
    "${install_dir}/kanban-cross-board-info-severity.patch",
    "${install_dir}/kanban-same-board-legacy-prose-diagnostic-cleanup.patch",
  ]:
    ensure => absent,
  }

  exec { 'cleanup_hermes_patch_artifacts':
    command => "/bin/rm -rf ${source_dir}/build ${broker_source_dir}/build ${broker_source_dir}/src/hermes_agent_request_broker.egg-info && /usr/bin/find ${source_dir} ${broker_source_dir} -name '*.orig' -delete && /usr/bin/find ${source_dir} ${broker_source_dir} -name '*.rej' -delete && /usr/bin/find ${source_dir} ${broker_source_dir} -name '*.pyc' -delete && /usr/bin/find ${source_dir} ${broker_source_dir} -name '__pycache__' -exec /bin/rm -rf {} +",
    onlyif  => "/bin/sh -c 'test -e ${source_dir}/build || test -e ${broker_source_dir}/build || test -e ${broker_source_dir}/src/hermes_agent_request_broker.egg-info || /usr/bin/find ${source_dir} ${broker_source_dir} -name \"*.orig\" -print -quit | /bin/grep -q . || /usr/bin/find ${source_dir} ${broker_source_dir} -name \"*.rej\" -print -quit | /bin/grep -q . || /usr/bin/find ${source_dir} ${broker_source_dir} -name \"*.pyc\" -print -quit | /bin/grep -q . || /usr/bin/find ${source_dir} ${broker_source_dir} -name \"__pycache__\" -print -quit | /bin/grep -q .'",
    require => [
      Vcsrepo[$source_dir],
      Vcsrepo[$broker_source_dir],
    ],
  }

  exec { 'cleanup_hermes_install_artifacts':
    command => "/bin/rm -rf ${source_dir}/hermes_agent.egg-info ${broker_source_dir}/src/hermes_agent_request_broker.egg-info && /usr/bin/find ${venv_dir}/lib/python*/site-packages -name '*.orig' -delete && /usr/bin/find ${venv_dir}/lib/python*/site-packages -name '*.rej' -delete",
    onlyif  => "/bin/sh -c 'test -e ${source_dir}/hermes_agent.egg-info || test -e ${broker_source_dir}/src/hermes_agent_request_broker.egg-info || /usr/bin/find ${venv_dir}/lib/python*/site-packages -name \"*.orig\" -print -quit | /bin/grep -q . || /usr/bin/find ${venv_dir}/lib/python*/site-packages -name \"*.rej\" -print -quit | /bin/grep -q .'",
    require => [
      Exec['install_hermes_agent'],
      Exec['install_hermes_agent_request_broker'],
    ],
  }

  exec { 'install_hermes_agent':
    command     => "${venv_pip} install --upgrade --force-reinstall ${source_dir} && git -C ${source_dir} rev-parse HEAD > ${git_revision_file}",
    unless      => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\" && ${venv_python} -c \"import importlib.metadata as m; m.version('python-multipart')\" && ${venv_python} -m pip check",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    path        => ['/bin', '/usr/bin'],
    require     => [
      Exec['cleanup_hermes_patch_artifacts'],
      Exec['create_hermes_venv'],
      File["${source_dir}/tools/agent_request_tool.py"],
      File["${source_dir}/tools/google_workspace_tool.py"],
      File["${source_dir}/tools/shopping_browser_tool.py"],
    ],
  }

  file { "${source_dir}/tools/agent_request_tool.py":
    ensure  => link,
    target  => "${broker_source_dir}/src/tools/agent_request_tool.py",
    require => [
      Vcsrepo[$source_dir],
      Vcsrepo[$broker_source_dir],
    ],
  }

  exec { 'install_hermes_agent_request_broker':
    command     => "${venv_pip} install --upgrade --force-reinstall ${broker_source_dir} && git -C ${broker_source_dir} rev-parse HEAD > ${broker_git_revision_file}",
    unless      => "test \"$(git -C ${broker_source_dir} rev-parse HEAD)\" = \"$(cat ${broker_git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent-request-broker'); import agent_request_broker.kanban_backend as kb; import agent_request_broker.common as c; assert hasattr(kb, 'trusted_accept_review'); assert hasattr(kb, 'resume_blocked_task_from_reply'); assert hasattr(kb, '_reply_prompt_stale_reason'); assert hasattr(kb, '_active_reply_prompts'); assert hasattr(kb, 'handle_telegram_unstuck'); assert hasattr(kb, 'TASK_ID_RE'); assert hasattr(kb, 'UNSTUCK_HELP_TERMS'); assert hasattr(kb, 'cleanup_terminal_task_resources'); assert hasattr(kb, 'cleanup_terminal_task_sweep'); assert hasattr(kb, 'delete_eyrie_registry_repository'); assert hasattr(kb, '_create_review_question_answer_task'); assert kb.event_label('commented') == 'comment'; assert kb.event_label('review_question_answer_needed') == 'review question answer needed'; assert hasattr(kb, 'ATTENTION_REQUIRED_NOTIFICATION_ACTIONS'); assert hasattr(kb, 'notification_urgency_detail'); assert kb.notification_urgency_detail('blocked')['telegram_disable_notification'] is False; assert kb.notification_urgency_detail('review_requested')['telegram_disable_notification'] is False; assert hasattr(c, '_telegram_send_voice_notification'); assert hasattr(c, '_voice_summary_part'); assert hasattr(c, '_text_to_speech_for_profile'); assert hasattr(kb, 'notification_board_label'); assert hasattr(kb, 'parse_callback_token'); assert hasattr(kb, 'open_blocking_child_error'); assert hasattr(kb, 'agent_request_task_completed'); assert hasattr(kb, 'sync_blocked_parent_requests_for_completed_task'); assert hasattr(kb, '_board_from_hermes_kanban_db'); assert hasattr(kb, 'redact_notification_line'); assert hasattr(kb, 'notifiable_index_for_task'); assert hasattr(kb, 'maybe_register_direct_kanban_fallback_review'); assert hasattr(kb, 'DIRECT_KANBAN_FALLBACK_PHRASES'); assert hasattr(kb, 'ensure_review_handoff_for_notification'); assert hasattr(kb, 'archive_completed_requests'); assert hasattr(kb, 'completed_archive_candidates'); assert hasattr(kb, 'remind_actionable_request'); assert hasattr(kb, 'latest_joy_visible_notification'); import os; os.environ['AGENT_REQUEST_KANBAN_BOARD']='agent-requests'; os.environ['AGENT_REQUEST_KANBAN_BOARD_OVERRIDE']='agent-requests-dev'; assert kb.board_name() == 'agent-requests-dev'; os.environ.pop('AGENT_REQUEST_KANBAN_BOARD_OVERRIDE', None); os.environ['HERMES_KANBAN_DB']='/tmp/hermes-kanban/boards/agent-requests-dev/kanban.db'; assert kb.board_name() == 'agent-requests-dev'; assert kb.validate_callback_token is not None\" && ${venv_python} -m pip check",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    path        => ['/bin', '/usr/bin'],
    require     => [
      Exec['cleanup_hermes_patch_artifacts'],
      Exec['create_hermes_venv'],
      Vcsrepo[$broker_source_dir],
    ],
  }

  file { "${source_dir}/tools/google_workspace_tool.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/google_workspace_tool.py',
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/shopping_browser_tool.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/shopping_browser_tool.py',
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  exec { 'build_hermes_tui':
    command     => "npm ci --silent --no-fund --no-audit --progress=false && npm run build && git -C ${source_dir} rev-parse HEAD > ${tui_revision_file}",
    cwd         => "${source_dir}/ui-tui",
    unless      => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${tui_revision_file} 2>/dev/null)\" && test -f ${source_dir}/ui-tui/dist/entry.js && test -d ${source_dir}/ui-tui/node_modules && /bin/grep -q 'RICH_OPEN_RE' ${source_dir}/ui-tui/dist/entry.js && /bin/grep -q 'NO_BANNER_LOGO' ${source_dir}/ui-tui/dist/entry.js",
    environment => [
      'HOME=/root',
      'NPM_CONFIG_CACHE=/root/.npm',
    ],
    path        => ['/bin', '/usr/bin', '/usr/sbin'],
    timeout     => 600,
    require     => [
      Vcsrepo[$source_dir],
    ],
  }

  file { '/usr/local/bin/hermes':
    ensure  => link,
    target  => "${venv_dir}/bin/hermes",
    require => Exec['install_hermes_agent'],
  }

  file { '/usr/local/bin/hermes-codex-auth-status':
    ensure => absent,
  }

  $nest::app::hermes::instances.each |String[1] $instance_name, Hash $instance_config| {
    $wrapper_profile = pick($instance_config['profile'], $instance_name)

    file { "/usr/local/bin/${wrapper_profile}":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => @("PY"),
        #!${venv_dir}/bin/python
        import os
        import sys

        os.environ['SHLVL'] = '1'
        os.environ['PYTHONPATH'] = '${source_dir}:${broker_source_dir}/src'
        os.execv('${venv_dir}/bin/hermes', ['${venv_dir}/bin/hermes', '--profile', '${wrapper_profile}', *sys.argv[1:]])
        | PY
      require => Exec['install_hermes_agent'],
    }

    file { "/usr/local/bin/${wrapper_profile}-agent-requests-dev":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => @("PY"),
        #!${venv_dir}/bin/python
        import os
        import sys

        os.environ['AGENT_REQUEST_KANBAN_BOARD'] = 'agent-requests-dev'
        os.environ['AGENT_REQUEST_KANBAN_BOARD_OVERRIDE'] = 'agent-requests-dev'
        os.environ['HERMES_KANBAN_BOARD'] = 'agent-requests-dev'
        os.environ['HERMES_KANBAN_DB'] = '/home/${nest::user}/.hermes/kanban/boards/agent-requests-dev/kanban.db'
        os.environ['SHLVL'] = '1'
        os.environ['PYTHONPATH'] = '${source_dir}:${broker_source_dir}/src'
        os.execv('${venv_dir}/bin/hermes', ['${venv_dir}/bin/hermes', '--profile', '${wrapper_profile}', *sys.argv[1:]])
        | PY
      require => Exec['install_hermes_agent_request_broker'],
    }
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

  exec { 'install_hermes_web_deps':
    command     => "${venv_pip} install '${source_dir}[web]'",
    unless      => "${venv_python} -c \"import fastapi, uvicorn\"",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    require     => Exec['install_hermes_agent'],
  }

  exec { 'install_hermes_pty_deps':
    command     => "${venv_pip} install '${source_dir}[pty]'",
    unless      => "${venv_python} -c \"import ptyprocess\"",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    require     => Exec['install_hermes_agent'],
  }

  exec { 'install_hermes_google_deps':
    command     => "${venv_pip} install '${source_dir}[google]'",
    unless      => "${venv_python} -c \"import googleapiclient, google_auth_oauthlib, google_auth_httplib2\"",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    require     => Exec['install_hermes_agent'],
  }

  nest::lib::package { 'media-video/ffmpeg':
    ensure => present,
    use    => ['opus'],
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

    file { $gws_dir:
      ensure => directory,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
    }
    ->
    exec { 'install_google_workspace_cli':
      command     => "${nodejs::npm_path} install @googleworkspace/cli@latest",
      unless      => "${nodejs::npm_path} list @googleworkspace/cli --depth=0 >/dev/null 2>&1 && ${nodejs::npm_path} outdated @googleworkspace/cli --depth=0 >/dev/null 2>&1",
      cwd         => $gws_dir,
      environment => ['HOME=/root'],
      require     => Class['nodejs'],
    }
    ->
    file { '/usr/local/bin/gws':
      ensure => link,
      target => "${gws_dir}/node_modules/.bin/gws",
    }

    exec { 'build_hermes_dashboard_web':
      command => "${nodejs::npm_path} install --silent && ${nodejs::npm_path} run build && git -C ${source_dir} rev-parse HEAD > ${web_revision_file}",
      unless  => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${web_revision_file} 2>/dev/null)\" && test -f ${source_dir}/hermes_cli/web_dist/index.html && /bin/grep -q 'Awaiting human review' ${source_dir}/hermes_cli/web_dist/assets/*.js",
      cwd     => "${source_dir}/web",
      path    => ['/bin', '/usr/bin', '/usr/sbin'],
      require => [
        Class['nodejs'],
        Vcsrepo[$source_dir],
      ],
    }
  }
}
