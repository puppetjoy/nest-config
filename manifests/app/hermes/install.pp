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

  $broker_patch_execs = [
    'patch_hermes_agent_request_review_handoff_flow',
    'patch_hermes_agent_request_worktree_cleanup',
    'patch_hermes_agent_request_telegram_unstuck',
    'patch_hermes_agent_request_telegram_voice_notifications',
    'patch_hermes_agent_request_recipient_profile_tts',
    'patch_hermes_agent_request_comment_label',
    'patch_hermes_agent_request_review_question_answer',
    'patch_hermes_agent_request_dev_board_labels',
    'patch_hermes_agent_request_blocking_child_review_guard',
    'patch_hermes_agent_request_blocking_child_wakeup',
    'patch_hermes_agent_request_superseded_review_parent',
    'patch_hermes_agent_request_stale_blocked_parent_reconcile',
    'patch_hermes_agent_request_dev_board_override',
    'patch_hermes_agent_request_dev_board_current_db',
    'patch_hermes_agent_request_notification_narrow_redaction',
    'patch_hermes_agent_request_child_task_notifications',
    'patch_hermes_agent_request_review_requested_attention',
    'patch_hermes_agent_request_future_milestone_dependency',
    'patch_hermes_agent_request_direct_kanban_fallback_review',
    'patch_hermes_agent_request_direct_kanban_fallback_review_test',
    'patch_hermes_agent_request_direct_kanban_reminder_fallback',
    'patch_hermes_agent_request_watchdog_actionable_reminder',
    'patch_hermes_agent_request_completed_archive_policy',
    'patch_hermes_agent_request_telegram_delivery_profile_routing',
  ]

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
    require => Exec[$broker_patch_execs],
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

  file { "${install_dir}/agent-request-review-handoff-flow.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-review-handoff-flow.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_review_handoff_flow':
    command => "/usr/sbin/git -C ${broker_source_dir} reset --hard HEAD && /bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej ${broker_source_dir}/bin/agent-request-accept-review && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-handoff-flow.patch",
    unless  => "/bin/grep -q 'agent_request_review_handoff' ${broker_source_dir}/src/tools/agent_request_tool.py && /bin/grep -q 'trusted_accept_review' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'REVIEW_ACCEPTANCE_PREFIX' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'REVIEW_BUTTON_ACTIONS' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'handle_telegram_reply' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'resume_blocked_task_from_reply' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q '_reply_prompt_stale_reason' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q '_active_reply_prompts' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py",
    require => [
      File["${install_dir}/agent-request-review-handoff-flow.patch"],
      Vcsrepo[$broker_source_dir],
    ],
  }

  file { "${install_dir}/agent-request-worktree-cleanup.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-worktree-cleanup.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_worktree_cleanup':
    command => "/usr/sbin/git -C ${broker_source_dir} reset --hard HEAD && /bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej ${broker_source_dir}/bin/agent-request-accept-review ${broker_source_dir}/bin/agent-request-cleanup-terminal-resources && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-handoff-flow.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-worktree-cleanup.patch",
    unless  => "/bin/grep -q 'cleanup_terminal_task_resources' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'cleanup_terminal_task_sweep' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'delete_eyrie_registry_repository' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_cleanup_deletes_merged_remote_branch_when_local_branch_and_workspace_are_absent' ${broker_source_dir}/tests/test_agent_request_broker.py && /bin/grep -q 'test_cleanup_eyrie_registry_deletion_is_env_gated_and_uses_docker_registry_v2' ${broker_source_dir}/tests/test_agent_request_broker.py && /bin/test -x ${broker_source_dir}/bin/agent-request-cleanup-terminal-resources",
    require => [
      File["${install_dir}/agent-request-worktree-cleanup.patch"],
      Exec['patch_hermes_agent_request_review_handoff_flow'],
    ],
  }

  file { "${install_dir}/agent-request-telegram-unstuck.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-telegram-unstuck.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_telegram_unstuck':
    command => "/usr/sbin/git -C ${broker_source_dir} reset --hard HEAD && /bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej ${broker_source_dir}/bin/agent-request-cleanup-terminal-resources && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-handoff-flow.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-worktree-cleanup.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-telegram-unstuck.patch",
    unless  => "/bin/grep -q 'TASK_ID_RE' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'UNSTUCK_HELP_TERMS' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_unstuck_with_task_id_attaches_steering' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-telegram-unstuck.patch"],
      Exec['patch_hermes_agent_request_worktree_cleanup'],
    ],
  }

  exec { 'patch_hermes_agent_request_telegram_voice_notifications':
    command => "/usr/sbin/git -C ${broker_source_dir} reset --hard HEAD && /bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/src/agent_request_broker/common.py.orig ${broker_source_dir}/src/agent_request_broker/common.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej ${broker_source_dir}/bin/agent-request-accept-review ${broker_source_dir}/bin/agent-request-cleanup-terminal-resources && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-handoff-flow.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-worktree-cleanup.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-telegram-unstuck.patch",
    unless  => "/bin/grep -q 'TASK_ID_RE' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'UNSTUCK_HELP_TERMS' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q '_VOICE_DANGLING_WORDS' ${broker_source_dir}/src/agent_request_broker/common.py && /bin/grep -q 'headline = re.sub(r\"^request' ${broker_source_dir}/src/agent_request_broker/common.py && /bin/grep -q 'reply_parameters' ${broker_source_dir}/src/agent_request_broker/common.py && /bin/grep -q 'test_voice_summary_prefers_complete_sentence_over_mid_clause_truncation' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      Exec['patch_hermes_agent_request_telegram_unstuck'],
    ],
  }

  file { "${install_dir}/agent-request-recipient-profile-tts.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-recipient-profile-tts.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_recipient_profile_tts':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/common.py.orig ${broker_source_dir}/src/agent_request_broker/common.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-recipient-profile-tts.patch",
    unless  => "/bin/grep -q '_text_to_speech_for_profile' ${broker_source_dir}/src/agent_request_broker/common.py && /bin/grep -q 'tts_profile' ${broker_source_dir}/src/agent_request_broker/common.py && /bin/grep -q 'test_telegram_voice_notification_uses_recipient_profile_tts_context' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-recipient-profile-tts.patch"],
      Exec['patch_hermes_agent_request_telegram_voice_notifications'],
    ],
  }

  file { "${install_dir}/agent-request-comment-label.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-comment-label.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_comment_label':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-comment-label.patch",
    unless  => "/bin/grep -q '\"commented\": \"comment\"' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py",
    require => [
      File["${install_dir}/agent-request-comment-label.patch"],
      Exec['patch_hermes_agent_request_recipient_profile_tts'],
    ],
  }

  file { "${install_dir}/agent-request-review-question-answer.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-review-question-answer.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_review_question_answer':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-question-answer.patch",
    unless  => "/bin/grep -q '_create_review_question_answer_task' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'review_question_answer_needed' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_review_question_reply_creates_actionable_answer_task_and_retires_prompt' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-review-question-answer.patch"],
      Exec['patch_hermes_agent_request_comment_label'],
    ],
  }

  file { "${install_dir}/agent-request-dev-board-labels.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-dev-board-labels.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_dev_board_labels':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-dev-board-labels.patch",
    unless  => "/bin/grep -q 'notification_board_label' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'parse_callback_token' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_dev_board_notifications_are_labeled_and_callbacks_route_to_dev_board' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-dev-board-labels.patch"],
      Exec['patch_hermes_agent_request_review_question_answer'],
    ],
  }

  file { "${install_dir}/agent-request-blocking-child-review-guard.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-blocking-child-review-guard.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_blocking_child_review_guard':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-blocking-child-review-guard.patch",
    unless  => "/bin/grep -q 'open_blocking_child_error' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_review_handoff_rejects_parent_with_open_blocking_child' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-blocking-child-review-guard.patch"],
      Exec['patch_hermes_agent_request_dev_board_labels'],
    ],
  }

  file { "${install_dir}/agent-request-blocking-child-wakeup.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-blocking-child-wakeup.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_blocking_child_wakeup':
    command => "/usr/sbin/git -C ${broker_source_dir} reset --hard HEAD && /bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/src/agent_request_broker/common.py.orig ${broker_source_dir}/src/agent_request_broker/common.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej ${broker_source_dir}/bin/agent-request-accept-review ${broker_source_dir}/bin/agent-request-cleanup-terminal-resources && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-handoff-flow.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-worktree-cleanup.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-telegram-unstuck.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-recipient-profile-tts.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-question-answer.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-dev-board-labels.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-blocking-child-review-guard.patch && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-blocking-child-wakeup.patch",
    unless  => "/bin/sh -c 'PYTHONPYCACHEPREFIX=/tmp/hermes-broker-pycache-puppet /opt/hermes-agent/venv/bin/python -m py_compile ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q agent_request_task_completed ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q test_completed_blocking_child_with_blocking_repair_relinks_parent_to_repair_path ${broker_source_dir}/tests/test_agent_request_broker.py'",
    require => [
      File["${install_dir}/agent-request-blocking-child-wakeup.patch"],
    ],
  }

  file { "${install_dir}/agent-request-superseded-review-parent.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-superseded-review-parent.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_superseded_review_parent':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-superseded-review-parent.patch",
    unless  => "/bin/grep -q 'superseded by the completed blocking-child path' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_completed_blocking_child_reconciles_superseded_parent_review_to_done' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-superseded-review-parent.patch"],
      Exec['patch_hermes_agent_request_blocking_child_wakeup'],
    ],
  }

  file { "${install_dir}/agent-request-stale-blocked-parent-reconcile.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-stale-blocked-parent-reconcile.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_stale_blocked_parent_reconcile':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-stale-blocked-parent-reconcile.patch",
    unless  => "/bin/grep -q 'sync_blocked_parent_requests_for_completed_task' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_completed_native_followup_reconciles_parent_blocked_on_stale_task_reference' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-stale-blocked-parent-reconcile.patch"],
      Exec['patch_hermes_agent_request_superseded_review_parent'],
    ],
  }

  file { "${install_dir}/agent-request-dev-board-override.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-dev-board-override.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_dev_board_override':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-dev-board-override.patch",
    unless  => "/bin/grep -q 'AGENT_REQUEST_KANBAN_BOARD_OVERRIDE' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_board_name_override_takes_precedence_over_profile_dotenv_board' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-dev-board-override.patch"],
      Exec['patch_hermes_agent_request_stale_blocked_parent_reconcile'],
    ],
  }

  file { "${install_dir}/agent-request-dev-board-current-db.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-dev-board-current-db.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_dev_board_current_db':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-dev-board-current-db.patch",
    unless  => "/bin/grep -q '_board_from_hermes_kanban_db' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_hermes_kanban_db_board_takes_precedence_over_profile_dotenv_board_for_notifications' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-dev-board-current-db.patch"],
      Exec['patch_hermes_agent_request_dev_board_override'],
    ],
  }

  file { "${install_dir}/agent-request-notification-narrow-redaction.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-notification-narrow-redaction.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_notification_narrow_redaction':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-notification-narrow-redaction.patch",
    unless  => "/bin/grep -q 'redact_notification_line' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_notification_sanitizer_redacts_narrowly_without_dropping_benign_context' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-notification-narrow-redaction.patch"],
      Exec['patch_hermes_agent_request_dev_board_current_db'],
    ],
  }

  file { "${install_dir}/agent-request-child-task-notifications.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-child-task-notifications.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_child_task_notifications':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-child-task-notifications.patch",
    unless  => "/bin/grep -q 'notifiable_index_for_task' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_notification_adapter_notifies_registered_child_task_events' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-child-task-notifications.patch"],
      Exec['patch_hermes_agent_request_notification_narrow_redaction'],
    ],
  }

  file { "${install_dir}/agent-request-review-requested-attention.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-review-requested-attention.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_review_requested_attention':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-requested-attention.patch",
    unless  => "/bin/grep -A10 'ATTENTION_REQUIRED_NOTIFICATION_ACTIONS' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py | /bin/grep -q 'review_requested'",
    require => [
      File["${install_dir}/agent-request-review-requested-attention.patch"],
      Exec['patch_hermes_agent_request_child_task_notifications'],
    ],
  }

  file { "${install_dir}/agent-request-future-milestone-dependency.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-future-milestone-dependency.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_future_milestone_dependency':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-future-milestone-dependency.patch",
    unless  => "/bin/grep -q 'child_parents = (parent_item.task_id,) if parent_item is not None and child_classification == \"future_milestone\" else ()' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_subrequest_future_milestone_waits_for_parent_dependency' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-future-milestone-dependency.patch"],
      Exec['patch_hermes_agent_request_review_requested_attention'],
      Exec['patch_hermes_agent_request_superseded_review_parent'],
    ],
  }

  file { "${install_dir}/agent-request-direct-kanban-fallback-review-code.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-direct-kanban-fallback-review-code.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  file { "${install_dir}/agent-request-direct-kanban-fallback-review-test.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-direct-kanban-fallback-review-test.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  file { "${install_dir}/agent-request-direct-kanban-review-phrase-coverage.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-direct-kanban-review-phrase-coverage.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  file { "${install_dir}/agent-request-direct-kanban-reminder-fallback.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-direct-kanban-reminder-fallback.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  file { "${install_dir}/agent-request-review-notification-binding.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-review-notification-binding.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  file { "${install_dir}/agent-request-telegram-delivery-profile-routing.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-telegram-delivery-profile-routing.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  file { "${install_dir}/agent-request-direct-kanban-fallback-review.patch":
    ensure => absent,
  }

  exec { 'patch_hermes_agent_request_direct_kanban_fallback_review':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-direct-kanban-fallback-review-code.patch",
    unless  => "/bin/grep -q 'maybe_register_direct_kanban_fallback_review' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py",
    require => [
      File["${install_dir}/agent-request-direct-kanban-fallback-review-code.patch"],
      Exec['patch_hermes_agent_request_future_milestone_dependency'],
    ],
  }

  exec { 'patch_hermes_agent_request_direct_kanban_fallback_review_test':
    command => "/bin/rm -f ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-direct-kanban-fallback-review-test.patch",
    unless  => "/bin/grep -q 'test_notification_adapter_registers_direct_kanban_fallback_review' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-direct-kanban-fallback-review-test.patch"],
      Exec['patch_hermes_agent_request_direct_kanban_fallback_review'],
    ],
  }

  exec { 'patch_hermes_agent_request_direct_kanban_review_phrase_coverage':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-direct-kanban-review-phrase-coverage.patch",
    unless  => "/bin/grep -q 'DIRECT_KANBAN_FALLBACK_PHRASES' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'direct corrective Kanban reviews are still indexed' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-direct-kanban-review-phrase-coverage.patch"],
      Exec['patch_hermes_agent_request_direct_kanban_fallback_review_test'],
    ],
  }

  exec { 'patch_hermes_agent_request_direct_kanban_reminder_fallback':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-direct-kanban-reminder-fallback.patch",
    unless  => "/bin/grep -q 'fallback_task_id = task_id' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'recent Joy-visible actionable notification already delivered' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-direct-kanban-reminder-fallback.patch"],
      Exec['patch_hermes_agent_request_direct_kanban_review_phrase_coverage'],
    ],
  }

  file { "${install_dir}/agent-request-watchdog-actionable-reminder.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-watchdog-actionable-reminder.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_watchdog_actionable_reminder':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/src/tools/agent_request_tool.py.orig ${broker_source_dir}/src/tools/agent_request_tool.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-watchdog-actionable-reminder.patch",
    unless  => "/bin/grep -q 'remind_actionable_request' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'agent_request_remind' ${broker_source_dir}/src/tools/agent_request_tool.py && /bin/grep -q 'test_watchdog_reminder_resends_actionable_notification_with_rate_limit' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-watchdog-actionable-reminder.patch"],
      Exec['patch_hermes_agent_request_direct_kanban_review_phrase_coverage'],
    ],
  }

  exec { 'patch_hermes_agent_request_review_notification_binding':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-review-notification-binding.patch",
    unless  => "/bin/grep -q 'ensure_review_handoff_for_notification' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_review_requested_kanban_event_synthesizes_review_before_buttons' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-review-notification-binding.patch"],
      Exec['patch_hermes_agent_request_watchdog_actionable_reminder'],
    ],
  }

  file { "${install_dir}/agent-request-completed-archive-policy.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/agent-request-completed-archive-policy.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_agent_request_completed_archive_policy':
    command => "/bin/rm -f ${broker_source_dir}/README.md.orig ${broker_source_dir}/README.md.rej ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej ${broker_source_dir}/bin/agent-request-archive-completed.orig ${broker_source_dir}/bin/agent-request-archive-completed.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-completed-archive-policy.patch",
    unless  => "/bin/grep -q 'archive_completed_requests' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_archive_completed_requests_dry_run_then_apply' ${broker_source_dir}/tests/test_agent_request_broker.py && test -x ${broker_source_dir}/bin/agent-request-archive-completed",
    require => [
      File["${install_dir}/agent-request-completed-archive-policy.patch"],
      Exec['patch_hermes_agent_request_review_notification_binding'],
    ],
  }

  exec { 'patch_hermes_agent_request_telegram_delivery_profile_routing':
    command => "/bin/rm -f ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.orig ${broker_source_dir}/src/agent_request_broker/kanban_backend.py.rej ${broker_source_dir}/tests/test_agent_request_broker.py.orig ${broker_source_dir}/tests/test_agent_request_broker.py.rej && /usr/bin/patch -N -p1 -d ${broker_source_dir} < ${install_dir}/agent-request-telegram-delivery-profile-routing.patch",
    unless  => "/bin/grep -q 'wrong_delivery_profile' ${broker_source_dir}/src/agent_request_broker/kanban_backend.py && /bin/grep -q 'test_reply_prompts_and_callbacks_are_scoped_to_delivery_profile' ${broker_source_dir}/tests/test_agent_request_broker.py",
    require => [
      File["${install_dir}/agent-request-telegram-delivery-profile-routing.patch"],
      Exec['patch_hermes_agent_request_completed_archive_policy'],
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
      Exec['patch_hermes_agent_request_review_handoff_flow'],
      Exec['patch_hermes_agent_request_worktree_cleanup'],
      Exec['patch_hermes_agent_request_telegram_unstuck'],
      Exec['patch_hermes_agent_request_telegram_voice_notifications'],
      Exec['patch_hermes_agent_request_recipient_profile_tts'],
      Exec['patch_hermes_agent_request_comment_label'],
      Exec['patch_hermes_agent_request_review_question_answer'],
      Exec['patch_hermes_agent_request_dev_board_labels'],
      Exec['patch_hermes_agent_request_blocking_child_review_guard'],
      Exec['patch_hermes_agent_request_dev_board_override'],
      Exec['patch_hermes_agent_request_dev_board_current_db'],
      Exec['patch_hermes_agent_request_notification_narrow_redaction'],
      Exec['patch_hermes_agent_request_child_task_notifications'],
      Exec['patch_hermes_agent_request_review_requested_attention'],
      Exec['patch_hermes_agent_request_future_milestone_dependency'],
      Exec['patch_hermes_agent_request_direct_kanban_review_phrase_coverage'],
      Exec['patch_hermes_agent_request_direct_kanban_reminder_fallback'],
      Exec['patch_hermes_agent_request_watchdog_actionable_reminder'],
      Exec['patch_hermes_agent_request_review_notification_binding'],
      Exec['patch_hermes_agent_request_completed_archive_policy'],
      Exec['patch_hermes_agent_request_telegram_delivery_profile_routing'],
      Exec['patch_hermes_agent_request_blocking_child_wakeup'],
      Exec['patch_hermes_agent_request_superseded_review_parent'],
      Exec['patch_hermes_agent_request_stale_blocked_parent_reconcile'],
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
