class nest::app::hermes::install {
  $install_dir       = $nest::app::hermes::install_dir
  $git_url           = $nest::app::hermes::git_url
  $git_ref           = $nest::app::hermes::git_ref
  $git_commit        = $nest::app::hermes::git_commit
  $venv_dir          = "${install_dir}/venv"
  $pm_enabled        = $nest::app::hermes::pm_enabled
  $venv_python       = $pm_enabled ? {
    true    => "${install_dir}/bin/hermes-python",
    default => "${venv_dir}/bin/python",
  }
  $python_ready      = $pm_enabled ? {
    true    => Package['dev-lang/python:3.14'],
    default => Python::Pyvenv[$venv_dir],
  }
  $runtime_ready     = $pm_enabled ? {
    true    => Exec['install_hermes_agent'],
    default => $python_ready,
  }
  $python_wrapper_ready = $pm_enabled ? {
    true    => Exec['install_hermes_agent'],
    default => $python_ready,
  }
  $venv_pip          = "${venv_dir}/bin/pip"
  $source_dir        = "${install_dir}/src"
  $broker_git_url    = $nest::app::hermes::broker_git_url
  $broker_git_ref    = $nest::app::hermes::broker_git_ref
  $broker_source_dir = "${install_dir}/agent-request-broker"
  $gws_dir           = '/opt/google-workspace-cli'
  $git_revision_file        = "${install_dir}/.installed-git-revision"
  $broker_git_revision_file = "${install_dir}/.installed-agent-request-broker-revision"
  $tui_revision_file        = "${install_dir}/.installed-tui-revision"
  $web_revision_file        = "${install_dir}/.installed-web-revision"
  $npm_dir                 = "${install_dir}/npm"
  $npm_command             = "/usr/bin/node ${npm_dir}/node_modules/npm/bin/npm-cli.js"
  $build_state             = "${venv_python} ${install_dir}/bin/hermes-build-state"
  $npm_cli                 = "${npm_dir}/node_modules/npm/bin/npm-cli.js"
  $python_world_atom       = $pm_enabled ? {
    true    => 'dev-lang/python:3.14',
    default => 'dev-lang/python:3.13',
  }

  if $pm_enabled {
    package { 'dev-lang/python:3.14':
      ensure => installed,
    }
  }

  # Retain the deployed interpreter until coordinated rollout activates PM.
  package { 'dev-lang/python:3.13':
    ensure => installed,
  }

  file_line { 'hermes-python-world':
    path => '/var/lib/portage/world',
    line => $python_world_atom,
    tag  => 'profile',
  }

  class { 'python':
    manage_python_package => false,
    manage_pip_package    => false,
    manage_venv_package   => false,
  }

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

  file { "${install_dir}/bin":
    ensure  => directory,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File[$install_dir],
  }

  if !$pm_enabled {
    python::pyvenv { $venv_dir:
      ensure      => present,
      version     => '3.13',
      python_path => '/usr/bin/python3.13',
      owner       => 'root',
      group       => 'root',
      require     => [
        Class['python'],
        File[$install_dir],
        Nest::Lib::Package['dev-python/virtualenv'],
        Package['dev-lang/python:3.13'],
      ],
    }

    # The module otherwise checks only for activate, not its interpreter.
    Exec <| title == "python_virtualenv_${venv_dir}" |> {
      creates => undef,
      unless  => "/bin/sh -c \"test -x ${venv_python} && ${venv_python} -c 'import sys; assert sys.version_info[:2] == (3, 13)'\"",
    }
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

  # vcsrepo only bootstraps the repository. All subsequent ref movement goes
  # through the journaled overlay-aware helper, including rolling updates.
  vcsrepo { $source_dir:
    ensure   => present,
    provider => git,
    source   => $git_url,
    tag      => 'hermes_source',
    require  => [
      File[$install_dir],
      Class['nest::base::git'],
      Exec['set_hermes_source_remote'],
    ],
  }

  file { "${install_dir}/bin/hermes-source-sync":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/hermes-source-sync.py',
    mode    => '0755',
    tag     => 'hermes_source',
    require => File["${install_dir}/bin"],
  }

  $source_pin_arg = $git_commit ? {
    undef   => '',
    default => " --commit ${git_commit}",
  }

  exec { 'sync_hermes_source':
    command => "/usr/bin/python3.13 ${install_dir}/bin/hermes-source-sync ${source_dir} ${git_ref}${source_pin_arg}",
    tag     => 'hermes_source',
    timeout => 600,
    require => [
      Vcsrepo[$source_dir],
      File["${install_dir}/bin/hermes-source-sync"],
      Package['dev-lang/python:3.13'],
    ],
  }

  if $git_commit {
    exec { 'verify_hermes_source_ref_pin':
      tag     => 'hermes_source',
      command => "/bin/sh -c 'echo Hermes source HEAD must match pinned commit ${git_commit} on ref ${git_ref} >&2; exit 1'",
      unless  => "/bin/sh -c 'test \"$(/usr/sbin/git -C ${source_dir} rev-parse HEAD)\" = ${git_commit} && /usr/sbin/git -C ${source_dir} merge-base --is-ancestor ${git_commit} origin/${git_ref}'",
      require => Exec['sync_hermes_source'],
    }
  }

  $source_ready = $git_commit ? {
    undef   => Exec['sync_hermes_source'],
    default => Exec['verify_hermes_source_ref_pin'],
  }

  # Order every managed overlay behind the transaction, even for tagged runs.
  # Keep this explicit list in step with hermes-source-sync.py's allowlist.
  $source_overlays = [
    'agent_request_tool.py', 'google_photos_tool.py', 'google_workspace_tool.py',
    'oauth_browser_tool.py', 'secure_browser_oauth_tool.py',
    'secure_browser_tool.py', 'firefox_ui_bridge.py',
    'secure_browser_local_bidi.py', 'secure_browser_bidi.py',
    'secure_browser_legacy_support.py', 'shopping_browser_tool.py',
  ]
  $source_overlay_paths = $source_overlays.map |$name| { "${source_dir}/tools/${name}" }
  Exec['sync_hermes_source'] -> File[$source_overlay_paths]
  Exec['sync_hermes_source'] -> Exec['build_hermes_tui']

  exec { 'set_hermes_agent_request_broker_remote':
    command => "/usr/sbin/git -C ${broker_source_dir} remote set-url origin ${broker_git_url}",
    onlyif  => "/bin/sh -c 'test -d ${broker_source_dir}/.git && test \"$(/usr/sbin/git -C ${broker_source_dir} remote get-url origin)\" != \"${broker_git_url}\"'",
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
    tag      => 'hermes_agent_request_broker_runtime',
    require  => [
      File[$install_dir],
      Class['nest::base::git'],
      Exec['set_hermes_agent_request_broker_remote'],
    ],
  }

  file { "${install_dir}/bin/hermes-python":
    ensure  => file,
    content => epp('nest/app/hermes/pm-python.sh.epp', {
      'install_dir' => $install_dir,
      'home_dir'    => "/home/${nest::user}/.hermes",
      'pm_enabled'  => $pm_enabled,
      'venv_dir'    => $venv_dir,
    }),
    mode    => '0755',
    require => [File["${install_dir}/bin"], $python_wrapper_ready],
  }

  if !$pm_enabled {
    exec { 'install_hermes_agent':
      # Setuptools' default editable finder runs after PathFinder. A stale
      # site-packages/hermes_cli directory can therefore win as a namespace
      # package and hide the source package. Compat mode adds the checkout to
      # sys.path directly while retaining the required editable install.
      command     => "${venv_pip} install --upgrade --force-reinstall --config-settings editable_mode=compat --editable ${source_dir} && git -C ${source_dir} rev-parse HEAD > ${git_revision_file}",
      unless      => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"from pathlib import Path; import hermes_cli, hermes_constants; assert Path(hermes_cli.__file__).resolve() == Path('${source_dir}/hermes_cli/__init__.py').resolve(); assert hermes_cli.__version__; assert Path(hermes_constants.__file__).resolve() == Path('${source_dir}/hermes_constants.py').resolve()\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\" && ${venv_python} -c \"import importlib.metadata as m; m.version('python-multipart')\" && ${venv_python} -m pip check",
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      path        => ['/bin', '/usr/bin'],
      require     => [
        $python_ready,
        File["${source_dir}/tools/agent_request_tool.py"],
        File["${source_dir}/tools/google_photos_tool.py"],
        File["${source_dir}/tools/google_workspace_tool.py"],
        File["${source_dir}/tools/oauth_browser_tool.py"],
        File["${source_dir}/tools/secure_browser_oauth_tool.py"],
        File["${source_dir}/tools/secure_browser_legacy_support.py"],
        File["${source_dir}/tools/secure_browser_tool.py"],
        File["${source_dir}/tools/shopping_browser_tool.py"],
      ],
    }
  } else {
    file { "${install_dir}/bin/hermes-pm":
      ensure  => file,
      source  => 'puppet:///modules/nest/app/hermes/hermes-pm.py',
      mode    => '0755',
      require => File["${install_dir}/bin"],
    }

    file { "${install_dir}/tools":
      ensure  => directory,
      owner   => $nest::user,
      group   => $nest::user,
      mode    => '0755',
      require => File[$install_dir],
    }

    contain nest::app::hermes::extracted_plugins

    # PM directory members with a build system install their own package. Make
    # the existing broker source an enabled dependency plugin so later normal
    # plugin transactions retain it in the same discovered dependency union.
    file { "${broker_source_dir}/plugin.yaml":
      ensure  => file,
      content => "name: nest-agent-request-broker\nversion: '1.0'\ndescription: Nest Agent Request broker runtime package\n",
      mode    => '0644',
      require => Vcsrepo[$broker_source_dir],
    }

    file { "${broker_source_dir}/__init__.py":
      ensure  => file,
      content => "def register(ctx):\n    pass\n",
      mode    => '0644',
      require => Vcsrepo[$broker_source_dir],
    }

    # Minimum safe ancestry, not permanent production HEAD pins. Run before
    # importing the candidate core or changing any active runtime wrapper.
    exec { 'verify_hermes_pm_checkpoint':
      command => "/usr/bin/python3.14 ${install_dir}/bin/hermes-pm verify ${install_dir}",
      require => [
        $python_ready,
        $source_ready,
        Vcsrepo[$broker_source_dir],
        File["${install_dir}/bin/hermes-pm"],
      ],
    }

    exec { 'install_hermes_agent':
      command     => "/usr/bin/python3.14 ${install_dir}/bin/hermes-pm sync ${install_dir}",
      unless      => "/usr/bin/python3.14 ${install_dir}/bin/hermes-pm check ${install_dir}",
      user        => $nest::user,
      environment => [
        "HOME=/home/${nest::user}",
        "HERMES_HOME=/home/${nest::user}/.hermes",
        "HERMES_RUNTIME_DIR=${install_dir}/tools",
      ],
      path        => ['/bin', '/usr/bin', '/usr/sbin'],
      timeout     => 3600,
      require     => [
        $python_ready,
        Vcsrepo[$source_dir],
        Vcsrepo[$broker_source_dir],
        $source_ready,
        Exec['verify_hermes_pm_checkpoint'],
        File["${source_dir}/tools/agent_request_tool.py"],
        File["${source_dir}/tools/google_photos_tool.py"],
        File["${source_dir}/tools/google_workspace_tool.py"],
        File["${source_dir}/tools/oauth_browser_tool.py"],
        File["${source_dir}/tools/secure_browser_oauth_tool.py"],
        File["${source_dir}/tools/secure_browser_legacy_support.py"],
        File["${source_dir}/tools/secure_browser_tool.py"],
        File["${source_dir}/tools/secure_browser_local_bidi.py"],
        File["${source_dir}/tools/secure_browser_bidi.py"],
        File["${source_dir}/tools/shopping_browser_tool.py"],
        File["${install_dir}/tools"],
        File["${broker_source_dir}/plugin.yaml"],
        File["${broker_source_dir}/__init__.py"],
        Class['nest::app::hermes::extracted_plugins'],
      ],
    }
  }

  file { "${source_dir}/tools/agent_request_tool.py":
    ensure  => link,
    target  => "${broker_source_dir}/src/tools/agent_request_tool.py",
    require => [
      Vcsrepo[$source_dir],
      Vcsrepo[$broker_source_dir],
    ],
  }

  if !$pm_enabled {
    exec { 'install_hermes_agent_request_broker':
      tag         => 'hermes_agent_request_broker_runtime',
      command     => "${venv_pip} install --upgrade --force-reinstall ${broker_source_dir} && git -C ${broker_source_dir} rev-parse HEAD > ${broker_git_revision_file}",
      unless      => "test \"$(git -C ${broker_source_dir} rev-parse HEAD)\" = \"$(cat ${broker_git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent-request-broker'); import agent_request_broker.kanban_backend as kb; import agent_request_broker.common as c; assert hasattr(kb, 'trusted_accept_review'); assert hasattr(kb, 'resume_blocked_task_from_reply'); assert hasattr(kb, '_reply_prompt_stale_reason'); assert hasattr(kb, '_active_reply_prompts'); assert hasattr(kb, 'handle_telegram_unstuck'); assert hasattr(kb, 'TASK_ID_RE'); assert hasattr(kb, 'UNSTUCK_HELP_TERMS'); assert hasattr(kb, 'cleanup_terminal_task_resources'); assert hasattr(kb, 'cleanup_terminal_task_sweep'); assert hasattr(kb, 'delete_eyrie_registry_repository'); assert hasattr(kb, '_create_review_question_answer_task'); assert kb.event_label('commented') == 'comment'; assert kb.event_label('review_question_answer_needed') == 'review question answer needed'; assert hasattr(kb, 'ATTENTION_REQUIRED_NOTIFICATION_ACTIONS'); assert hasattr(kb, 'notification_urgency_detail'); assert kb.notification_urgency_detail('blocked')['telegram_disable_notification'] is False; assert kb.notification_urgency_detail('review_requested')['telegram_disable_notification'] is False; assert hasattr(c, '_telegram_send_voice_notification'); assert hasattr(c, '_voice_summary_part'); assert hasattr(c, '_text_to_speech_for_profile'); assert hasattr(kb, 'notification_board_label'); assert hasattr(kb, 'parse_callback_token'); assert hasattr(kb, 'open_blocking_child_error'); assert hasattr(kb, 'agent_request_task_completed'); assert hasattr(kb, 'sync_blocked_parent_requests_for_completed_task'); assert hasattr(kb, '_board_from_hermes_kanban_db'); assert hasattr(kb, 'redact_notification_line'); assert hasattr(kb, 'notifiable_index_for_task'); assert hasattr(kb, 'maybe_register_direct_kanban_fallback_review'); assert hasattr(kb, 'DIRECT_KANBAN_FALLBACK_PHRASES'); assert hasattr(kb, 'ensure_review_handoff_for_notification'); assert hasattr(kb, 'archive_completed_requests'); assert hasattr(kb, 'completed_archive_candidates'); assert hasattr(kb, 'remind_actionable_request'); assert hasattr(kb, 'latest_joy_visible_notification'); import os; os.environ['AGENT_REQUEST_KANBAN_BOARD']='agent-requests'; os.environ['AGENT_REQUEST_KANBAN_BOARD_OVERRIDE']='agent-requests-dev'; assert kb.board_name() == 'agent-requests-dev'; os.environ.pop('AGENT_REQUEST_KANBAN_BOARD_OVERRIDE', None); os.environ['HERMES_KANBAN_DB']='/tmp/hermes-kanban/boards/agent-requests-dev/kanban.db'; assert kb.board_name() == 'agent-requests-dev'; assert kb.validate_callback_token is not None\" && ${venv_python} -m pip check",
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      path        => ['/bin', '/usr/bin'],
      require     => [
        $python_ready,
        Vcsrepo[$broker_source_dir],
      ],
    }
  } else {
    exec { 'install_hermes_agent_request_broker':
      command => "${venv_python} -c 'import agent_request_broker.kanban_backend'",
      unless  => "${venv_python} -c 'import agent_request_broker.kanban_backend'",
      require => Exec['install_hermes_agent'],
    }
  }

  file { "${source_dir}/tools/google_workspace_tool.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/google_workspace_tool.py',
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/google_photos_tool.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/google_photos_tool.py',
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${install_dir}/bin/google-photos-oauth":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/google-photos-oauth.py',
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => [
      File["${install_dir}/bin"],
      $python_ready,
    ],
  }

  file { "${install_dir}/bin/manage-hermes-env":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/manage-hermes-env.py',
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/manage-glab-config":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/manage-glab-config.py',
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File["${install_dir}/bin"],
  }

  file { "${source_dir}/tools/secure_browser_oauth_tool.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/secure_browser_oauth_tool.py',
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/oauth_browser_tool.py":
    ensure  => absent,
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/secure_browser_tool.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/secure_browser_tool.py',
    # A source-only checkout overwrites this tracked fork file too. Restore
    # the adapter in that same transaction, not at the next full Puppet run.
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => [Vcsrepo[$source_dir], File["${source_dir}/tools/firefox_ui_bridge.py"]],
  }

  # Bridge-only updates must not restart the owner-shared Firefox process.
  if $nest::app::hermes::firefox_bridge_token {
    file { "${install_dir}/firefox-bridge-token":
      ensure    => file,
      content   => $nest::app::hermes::firefox_bridge_token,
      tag       => 'hermes_firefox_bridge',
      mode      => '0640',
      owner     => 'root',
      group     => $nest::user,
      show_diff => false,
      require   => File[$install_dir],
    }
  }

  file { "${source_dir}/tools/firefox_ui_bridge.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/firefox-browser/firefox-ui-bridge.py',
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/secure_browser_local_bidi.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/secure_browser_local_bidi.py',
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/secure_browser_bidi.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/secure_browser_bidi.py',
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/secure_browser_legacy_support.py":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/secure_browser_legacy_support.py',
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    mode    => '0644',
    owner   => 'root',
    group   => 'root',
    require => Vcsrepo[$source_dir],
  }

  file { "${source_dir}/tools/shopping_browser_tool.py":
    ensure  => absent,
    tag     => ['hermes_firefox_bridge', 'hermes_source'],
    require => Vcsrepo[$source_dir],
  }

  include 'nodejs'

  file { $npm_dir:
    ensure  => directory,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File[$install_dir],
  }

  # Keep Hermes' supported npm separate from Gentoo's packaged npm.
  exec { 'install_hermes_npm':
    command     => "${nodejs::npm_path} install --prefix ${npm_dir} --no-save --package-lock=false --no-fund --no-audit npm@11.17.0",
    unless      => "test \"$(${npm_command} --version)\" = 11.17.0",
    environment => ['HOME=/root'],
    path        => ['/bin', '/usr/bin'],
    require     => [Class['nodejs'], File[$npm_dir]],
  }

  file { "${install_dir}/bin/hermes-build-state":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/hermes-build-state.py',
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    require => File["${install_dir}/bin"],
  }

  file { "${install_dir}/bin/hermes-frontend-build":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/hermes-frontend-build.py',
    mode    => '0755',
    require => File["${install_dir}/bin"],
  }

  # Source installs need upstream release tags: the fork remote carries only
  # rolling branches. VersionInfo reads the package version at the reachable tag.
  exec { 'fetch_hermes_release_metadata':
    command => "/usr/sbin/git -C ${source_dir} fetch --no-tags https://github.com/NousResearch/hermes-agent.git 'refs/tags/v*:refs/tags/v*'",
    require => $source_ready,
    timeout => 600,
  }

  $frontend_build = "${venv_python} ${install_dir}/bin/hermes-frontend-build"
  $frontend_env = [
    "HOME=/home/${nest::user}",
    "HERMES_HOME=/home/${nest::user}/.hermes",
    "HERMES_RUNTIME_DIR=${install_dir}/tools",
  ]

  # Relevant workspace inputs and output bytes, not UI copy or minified
  # identifiers, establish whether the last successful build is still valid.
  $build_hermes_tui_command = $pm_enabled ? {
    true    => "${frontend_build} build ${source_dir} tui",
    default => "${npm_command} ci --silent --no-fund --no-audit --progress=false && ${npm_command} run build && ${build_state} record ${source_dir} tui ${tui_revision_file}.json ${npm_cli} && git -C ${source_dir} rev-parse HEAD > ${tui_revision_file}",
  }

  $build_hermes_tui_unless = $pm_enabled ? {
    true    => "${frontend_build} check ${source_dir} tui",
    default => "${build_state} check ${source_dir} tui ${tui_revision_file}.json ${npm_cli}",
  }

  $build_hermes_tui_environment = $pm_enabled ? {
    true    => $frontend_env,
    default => ['HOME=/root', 'NPM_CONFIG_CACHE=/root/.npm'],
  }

  exec { 'build_hermes_tui':
    command     => $build_hermes_tui_command,
    cwd         => "${source_dir}/ui-tui",
    unless      => $build_hermes_tui_unless,
    environment => $build_hermes_tui_environment,
    path        => ['/bin', '/usr/bin', '/usr/sbin'],
    timeout     => 600,
    require     => [
      Vcsrepo[$source_dir],
      Exec['install_hermes_npm'],
      File["${install_dir}/bin/hermes-build-state"],
      File["${install_dir}/bin/hermes-frontend-build"],
      $runtime_ready,
    ],
  }

  file { '/usr/local/bin/hermes':
    ensure  => file,
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => epp('nest/app/hermes/cli-wrapper.sh.epp', {
      'venv_dir'       => $venv_dir,
      'pm_enabled'     => $pm_enabled,
      'install_dir'    => $install_dir,
      'ca_bundle_file' => $nest::app::hermes::ca_bundle_file,
    }),
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
      content => epp('nest/app/hermes/profile-wrapper.py.epp', {
        'venv_dir'          => $venv_dir,
        'pm_enabled'        => $pm_enabled,
        'install_dir'       => $install_dir,
        'source_dir'        => $source_dir,
        'broker_source_dir' => $broker_source_dir,
        'profile'           => $wrapper_profile,
        'user'              => $nest::user,
      }),
      require => Exec['install_hermes_agent'],
    }

    file { "/usr/local/bin/${wrapper_profile}-agent-requests-dev":
      ensure  => file,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      content => epp('nest/app/hermes/profile-wrapper.py.epp', {
        'venv_dir'          => $venv_dir,
        'pm_enabled'        => $pm_enabled,
        'install_dir'       => $install_dir,
        'source_dir'        => $source_dir,
        'broker_source_dir' => $broker_source_dir,
        'profile'           => $wrapper_profile,
        'user'              => $nest::user,
        'dev_board'         => true,
      }),
      require => Exec['install_hermes_agent_request_broker'],
    }
  }

  if !$pm_enabled {
    python::pip { 'hermes-agent-telegram-deps':
      ensure      => '22.6',
      pkgname     => 'python-telegram-bot',
      extras      => ['webhooks'],
      virtualenv  => $venv_dir,
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      require     => Exec['install_hermes_agent'],
    }

    python::pip { 'hermes-agent-honcho-deps':
      ensure      => present,
      pkgname     => 'honcho-ai',
      virtualenv  => $venv_dir,
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      require     => Exec['install_hermes_agent'],
    }

    exec { 'install_hermes_web_deps':
      command     => "${venv_pip} install --config-settings editable_mode=compat --editable '${source_dir}[web]'",
      unless      => "${venv_python} -c \"import fastapi, uvicorn\"",
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      require     => Exec['install_hermes_agent'],
    }

    exec { 'install_hermes_firecrawl_deps':
      command     => "${venv_pip} install --config-settings editable_mode=compat --editable '${source_dir}[firecrawl]'",
      unless      => "${venv_python} -c \"import firecrawl\"",
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      require     => Exec['install_hermes_agent'],
    }

    exec { 'install_hermes_pty_deps':
      command     => "${venv_pip} install --config-settings editable_mode=compat --editable '${source_dir}[pty]'",
      unless      => "${venv_python} -c \"import ptyprocess\"",
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      require     => Exec['install_hermes_agent'],
    }

    exec { 'install_hermes_google_deps':
      command     => "${venv_pip} install --config-settings editable_mode=compat --editable '${source_dir}[google]'",
      unless      => "${venv_python} -c \"import googleapiclient, google_auth_oauthlib, google_auth_httplib2\"",
      environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
      require     => Exec['install_hermes_agent'],
    }
  }

  nest::lib::package { 'media-video/ffmpeg':
    ensure => present,
    use    => ['opus'],
  }

  if $facts['profile']['architecture'] == 'amd64' {
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

    $build_hermes_dashboard_web_command = $pm_enabled ? {
      true    => "${frontend_build} build ${source_dir} web",
      default => "${npm_command} ci --silent --no-fund --no-audit --progress=false && ${npm_command} run build && ${build_state} record ${source_dir} web ${web_revision_file}.json ${npm_cli} && git -C ${source_dir} rev-parse HEAD > ${web_revision_file}",
    }

    $build_hermes_dashboard_web_unless = $pm_enabled ? {
      true    => "${frontend_build} check ${source_dir} web",
      default => "${build_state} check ${source_dir} web ${web_revision_file}.json ${npm_cli}",
    }

    $build_hermes_dashboard_web_environment = $pm_enabled ? {
      true    => $frontend_env,
      default => ['HOME=/root'],
    }

    exec { 'build_hermes_dashboard_web':
      # Both workspaces consume the root lockfile. Do not rewrite a shared
      # build input with npm install after recording the TUI build state.
      command     => $build_hermes_dashboard_web_command,
      unless      => $build_hermes_dashboard_web_unless,
      environment => $build_hermes_dashboard_web_environment,
      cwd         => "${source_dir}/web",
      path        => ['/bin', '/usr/bin', '/usr/sbin'],
      require     => [
        Class['nodejs'],
        Vcsrepo[$source_dir],
        Exec['install_hermes_npm'],
        Exec['build_hermes_tui'],
        File["${install_dir}/bin/hermes-build-state"],
        File["${install_dir}/bin/hermes-frontend-build"],
        $runtime_ready,
      ],
    }
  }
}
