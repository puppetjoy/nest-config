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
  $runtime_ready     = Exec['install_hermes_agent']
  $python_wrapper_ready = $pm_enabled ? {
    true    => Exec['install_hermes_agent'],
    default => Exec['install_hermes_agent_request_broker'],
  }
  $source_dir        = "${install_dir}/src"
  $external_requirements = "${install_dir}/.external-runtime-requirements.txt"
  $external_environment = [
    "UV_PROJECT_ENVIRONMENT=${venv_dir}",
    'UV_PYTHON_DOWNLOADS=never',
    'UV_NO_MANAGED_PYTHON=1',
  ]
  $external_check = "/usr/bin/uv sync --project ${source_dir} --python ${venv_python} --locked --extra all --extra telegram --extra firecrawl --no-default-groups --inexact --check --no-python-downloads --no-managed-python --config-settings editable_mode=compat"
  $broker_git_url    = $nest::app::hermes::broker_git_url
  $broker_git_ref    = $nest::app::hermes::broker_git_ref
  $broker_source_dir = "${install_dir}/agent-request-broker"
  $gws_dir           = '/opt/google-workspace-cli'
  $git_revision_file        = "${install_dir}/.installed-git-revision"
  $broker_git_revision_file = "${install_dir}/.installed-agent-request-broker-revision"
  $tui_revision_file        = "${install_dir}/.installed-tui-revision"
  $web_revision_file        = "${install_dir}/.installed-web-revision"
  include 'nodejs'

  $npm_dir                 = "${install_dir}/npm"
  $npm_command             = $pm_enabled ? {
    true    => "/usr/bin/node ${npm_dir}/node_modules/npm/bin/npm-cli.js",
    default => $nodejs::npm_path,
  }
  $npm_cli                 = $pm_enabled ? {
    true    => "${npm_dir}/node_modules/npm/bin/npm-cli.js",
    default => $nodejs::npm_path,
  }
  $build_state             = "${venv_python} ${install_dir}/bin/hermes-build-state"
  $python_world_atom       = 'dev-lang/python:3.14'

  package { 'dev-lang/python:3.14':
    ensure => installed,
  }

  # Retain the deployed interpreter until live replacement validation is accepted.
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
      version     => '3.14',
      python_path => '/usr/bin/python3.14',
      owner       => 'root',
      group       => 'root',
      require     => [
        Class['python'],
        File[$install_dir],
        Nest::Lib::Package['dev-python/virtualenv'],
        Package['dev-lang/python:3.14'],
      ],
    }

    # The module otherwise checks only for activate, not its interpreter.
    Exec <| title == "python_virtualenv_${venv_dir}" |> {
      creates => undef,
      unless  => "/bin/sh -c \"test -x ${venv_python} && ${venv_python} -c 'import sys; assert sys.version_info[:2] == (3, 14)'\"",
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

  if !$pm_enabled {
    # Use upstream ownership metadata only after the pinned commit has passed
    # the source-ref ancestry guard, and before installing or launching it.
    exec { 'write_hermes_external_install_stamp':
      command => "/usr/bin/python3.14 ${source_dir}/scripts/write_install_stamp.py --output ${source_dir}/install-stamp.json --commit $(/usr/sbin/git -C ${source_dir} rev-parse HEAD) --branch ${git_ref} --update-mechanism external",
      unless  => "/usr/bin/python3.14 -c 'import json,pathlib,subprocess; p=pathlib.Path(\"${source_dir}/install-stamp.json\"); d=json.loads(p.read_text()); assert d.get(\"updateMechanism\")==\"external\" and d.get(\"commit\")==subprocess.check_output([\"/usr/sbin/git\",\"-C\",\"${source_dir}\",\"rev-parse\",\"HEAD\"],text=True).strip()'",
      require => [$python_ready, $source_ready],
    }
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

  contain nest::app::hermes::extracted_plugins

  # Both installation owners register the same broker plugin and hooks
  file { "${broker_source_dir}/plugin.yaml":
    ensure  => file,
    content => "name: nest-agent-request-broker\nversion: '1.0'\ndescription: Nest Agent Request broker runtime package\n",
    mode    => '0644',
    require => Vcsrepo[$broker_source_dir],
  }

  file { "${broker_source_dir}/__init__.py":
    ensure  => file,
    content => "from agent_request_broker.blocked_writer_plugin import register\n",
    mode    => '0644',
    require => Vcsrepo[$broker_source_dir],
  }


  if !$pm_enabled {
    ensure_resource('nest::lib::package', 'dev-python/uv', {
      'ensure' => 'present',
    })

    # Export the accepted lock without resolving a replacement dependency graph
    exec { 'export_hermes_external_requirements':
      command     => "/usr/bin/uv export --project ${source_dir} --locked --extra all --extra telegram --extra firecrawl --no-default-groups --no-emit-project --no-hashes --no-python-downloads --output-file ${external_requirements} >/dev/null",
      environment => $external_environment,
      require     => [$python_ready, $source_ready, Nest::Lib::Package['dev-python/uv']],
    }

    exec { 'install_hermes_agent':
      # Preserve upstream's deliberate overrides and exact transitive lock pins
      # Compat editable mode keeps the managed checkout ahead of stale packages
      command     => "/usr/bin/uv pip install --python ${venv_python} --requirements ${external_requirements} --overrides ${external_requirements} --reinstall-package hermes-agent --config-settings editable_mode=compat --editable '${source_dir}[all,telegram,firecrawl]' 'honcho-ai==2.8.0' && ${external_check} && git -C ${source_dir} rev-parse HEAD > ${git_revision_file}",
      unless      => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"from pathlib import Path; import hermes_cli, hermes_constants; assert Path(hermes_cli.__file__).resolve() == Path('${source_dir}/hermes_cli/__init__.py').resolve(); assert hermes_cli.__version__; assert Path(hermes_constants.__file__).resolve() == Path('${source_dir}/hermes_constants.py').resolve()\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\" && ${venv_python} -c \"import importlib.metadata as m; m.version('python-multipart'); assert m.version('honcho-ai') == '2.8.0'; import honcho, telegram, firecrawl, ptyprocess, fastapi, uvicorn, googleapiclient\" && ${external_check}",
      environment => $external_environment,
      path        => ['/bin', '/usr/bin'],
      require     => [
        $python_ready,
        Exec['write_hermes_external_install_stamp'],
        Exec['export_hermes_external_requirements'],
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
      command     => "/usr/bin/uv pip install --python ${venv_python} --requirements ${external_requirements} --overrides ${external_requirements} --reinstall-package hermes-agent-request-broker ${broker_source_dir} && ${external_check} && git -C ${broker_source_dir} rev-parse HEAD > ${broker_git_revision_file}",
      unless      => "test \"$(git -C ${broker_source_dir} rev-parse HEAD)\" = \"$(cat ${broker_git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent-request-broker'); import agent_request_broker.kanban_backend; import agent_request_broker.gitlab_mr_note_poller\" && ${external_check}",
      environment => $external_environment,
      path        => ['/bin', '/usr/bin'],
      require     => [
        $python_ready,
        Exec['install_hermes_agent'],
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

  if $pm_enabled {
    file { $npm_dir:
      ensure  => directory,
      mode    => '0755',
      owner   => 'root',
      group   => 'root',
      require => File[$install_dir],
    }

    # PM generation uses its supported npm; external installs use Gentoo's npm.
    exec { 'install_hermes_npm':
      command     => "${nodejs::npm_path} install --prefix ${npm_dir} --no-save --package-lock=false --no-fund --no-audit npm@11.17.0",
      unless      => "test \"$(${npm_command} --version)\" = 11.17.0",
      environment => ['HOME=/root'],
      path        => ['/bin', '/usr/bin'],
      require     => [Class['nodejs'], File[$npm_dir]],
    }
  }

  $npm_ready = $pm_enabled ? {
    true    => Exec['install_hermes_npm'],
    default => Class['nodejs'],
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
      $npm_ready,
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

  # Production entry points must not be shadowed by a checkout's editable install.
  ['hermes', 'hermes-agent', 'hermes-acp'].each |String $entry| {
    file { "/home/${nest::user}/.local/bin/${entry}":
      ensure  => absent,
      require => File['/usr/local/bin/hermes'],
    }
  }

  file { '/usr/local/bin/hermes-agent':
    ensure  => file,
    mode    => '0755',
    content => "#!/bin/sh\nexec ${venv_python} -m run_agent \"\$@\"\n",
    require => File['/usr/local/bin/hermes'],
  }

  file { '/usr/local/bin/hermes-acp':
    ensure  => file,
    mode    => '0755',
    content => "#!/bin/sh\nexec /usr/local/bin/hermes acp \"\$@\"\n",
    require => File['/usr/local/bin/hermes'],
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
    # The service's existing readiness edge verifies the locked PTY dependency
    exec { 'install_hermes_pty_deps':
      command => "${venv_python} -c 'import ptyprocess'",
      unless  => "${venv_python} -c 'import ptyprocess'",
      require => Exec['install_hermes_agent'],
    }
  }

  nest::lib::package { 'media-video/ffmpeg':
    ensure => present,
    use    => ['opus'],
  }

  if $facts['profile']['architecture'] == 'amd64' {
    # Standard and secure browser workflows use the managed Firefox services
    nest::lib::package { 'www-client/google-chrome':
      ensure => absent,
    }

    file { '/usr/local/bin/google-chrome':
      ensure => absent,
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
        $npm_ready,
        Exec['build_hermes_tui'],
        File["${install_dir}/bin/hermes-build-state"],
        File["${install_dir}/bin/hermes-frontend-build"],
        $runtime_ready,
      ],
    }
  }
}
