class nest::app::hermes::install {
  $install_dir       = $nest::app::hermes::install_dir
  $git_url           = $nest::app::hermes::git_url
  $git_ref           = $nest::app::hermes::git_ref
  $venv_dir          = "${install_dir}/venv"
  $venv_python       = "${venv_dir}/bin/python"
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
    require  => [
      File[$install_dir],
      Class['nest::base::git'],
      Exec['set_hermes_agent_request_broker_remote'],
    ],
  }

  exec { 'install_hermes_agent':
    command     => "${venv_pip} install --upgrade --force-reinstall ${source_dir} && git -C ${source_dir} rev-parse HEAD > ${git_revision_file}",
    unless      => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent')\" && /bin/grep -q 'app.state.allow_public = allow_public' ${venv_dir}/lib/python*/site-packages/hermes_cli/web_server.py && /bin/grep -q 'if _pl <= 0:' ${venv_dir}/lib/python*/site-packages/gateway/run.py && /bin/grep -q '_banner_hero_renderable' ${venv_dir}/lib/python*/site-packages/hermes_cli/banner.py && /bin/grep -q 'banner_subtitle' ${venv_dir}/lib/python*/site-packages/hermes_cli/banner.py && /bin/grep -q 'discover_builtin_tools()' ${venv_dir}/lib/python*/site-packages/cli.py",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    path        => ['/bin', '/usr/bin'],
    require     => [
      Exec['create_hermes_venv'],
      Exec['patch_hermes_dashboard_insecure_websockets'],
      Exec['patch_hermes_telegram_tool_preview_length'],
      Exec['patch_hermes_banner_hero_renderable'],
      Exec['patch_hermes_banner_logo_suppression'],
      Exec['patch_hermes_cli_custom_toolset_validation'],
      File["${source_dir}/tools/agent_request_tool.py"],
      File["${source_dir}/tools/google_workspace_tool.py"],
    ],
  }

  file { "${install_dir}/dashboard-insecure-websockets.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/dashboard-insecure-websockets.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_dashboard_insecure_websockets':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/dashboard-insecure-websockets.patch",
    unless  => "/bin/grep -q 'app.state.allow_public = allow_public' ${source_dir}/hermes_cli/web_server.py && /bin/grep -q 'getattr(app.state, \"allow_public\", False)' ${source_dir}/hermes_cli/web_server.py",
    require => [
      File["${install_dir}/dashboard-insecure-websockets.patch"],
      Vcsrepo[$source_dir],
    ],
  }

  file { "${install_dir}/telegram-tool-preview-length.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/telegram-tool-preview-length.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_telegram_tool_preview_length':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/telegram-tool-preview-length.patch",
    unless  => "/bin/grep -q 'if _pl <= 0:' ${source_dir}/gateway/run.py",
    require => [
      File["${install_dir}/telegram-tool-preview-length.patch"],
      Vcsrepo[$source_dir],
    ],
  }

  file { "${install_dir}/banner-hero-renderable.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/banner-hero-renderable.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_banner_hero_renderable':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/banner-hero-renderable.patch",
    unless  => "/bin/grep -q '_banner_hero_renderable' ${source_dir}/hermes_cli/banner.py && /bin/grep -q 'left_content = Group' ${source_dir}/hermes_cli/banner.py",
    require => [
      File["${install_dir}/banner-hero-renderable.patch"],
      Vcsrepo[$source_dir],
    ],
  }

  file { "${install_dir}/banner-logo-suppression.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/banner-logo-suppression.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_banner_logo_suppression':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/banner-logo-suppression.patch",
    unless  => "/bin/grep -q 'banner_subtitle' ${source_dir}/hermes_cli/banner.py && /bin/grep -q '__none__' ${source_dir}/hermes_cli/banner.py",
    require => [
      File["${install_dir}/banner-logo-suppression.patch"],
      Exec['patch_hermes_banner_hero_renderable'],
    ],
  }

  file { "${install_dir}/cli-discover-custom-toolsets-before-validation.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/cli-discover-custom-toolsets-before-validation.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_cli_custom_toolset_validation':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/cli-discover-custom-toolsets-before-validation.patch",
    unless  => "/bin/grep -q 'Profile-managed platform_toolsets may' ${source_dir}/cli.py",
    require => [
      File["${install_dir}/cli-discover-custom-toolsets-before-validation.patch"],
      Vcsrepo[$source_dir],
    ],
  }

  file { "${install_dir}/dashboard-rich-art-spans.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/dashboard-rich-art-spans.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_dashboard_rich_art_spans':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/dashboard-rich-art-spans.patch",
    unless  => "/bin/grep -q 'RICH_OPEN_RE' ${source_dir}/ui-tui/src/banner.ts && /bin/grep -q 'backgroundColor={bg || undefined}' ${source_dir}/ui-tui/src/components/branding.tsx",
    require => [
      File["${install_dir}/dashboard-rich-art-spans.patch"],
      Vcsrepo[$source_dir],
    ],
  }

  file { "${install_dir}/dashboard-chat-truecolor-env.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/dashboard-chat-truecolor-env.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_dashboard_chat_truecolor_env':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/dashboard-chat-truecolor-env.patch",
    unless  => "/bin/grep -q 'COLORTERM.*truecolor' ${source_dir}/hermes_cli/web_server.py",
    require => [
      File["${install_dir}/dashboard-chat-truecolor-env.patch"],
      Vcsrepo[$source_dir],
    ],
  }

  file { "${install_dir}/dashboard-skin-branding.patch":
    ensure => file,
    source => 'puppet:///modules/nest/app/hermes/dashboard-skin-branding.patch',
    mode   => '0644',
    owner  => 'root',
    group  => 'root',
  }

  exec { 'patch_hermes_dashboard_skin_branding':
    command => "/usr/bin/patch -N -p1 -d ${source_dir} < ${install_dir}/dashboard-skin-branding.patch",
    unless  => "/bin/grep -q 'NO_BANNER_LOGO' ${source_dir}/ui-tui/src/components/branding.tsx && /bin/grep -q 'branding.banner_subtitle' ${source_dir}/ui-tui/src/theme.ts",
    require => [
      File["${install_dir}/dashboard-skin-branding.patch"],
      Vcsrepo[$source_dir],
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
    unless      => "test \"$(git -C ${broker_source_dir} rev-parse HEAD)\" = \"$(cat ${broker_git_revision_file} 2>/dev/null)\" && ${venv_python} -c \"import importlib.metadata as m; m.version('hermes-agent-request-broker'); import agent_request_broker\"",
    environment => ['PIP_DISABLE_PIP_VERSION_CHECK=1'],
    path        => ['/bin', '/usr/bin'],
    require     => [
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
      Exec['patch_hermes_dashboard_rich_art_spans'],
      Exec['patch_hermes_dashboard_skin_branding'],
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
        os.execv('${venv_dir}/bin/hermes', ['${venv_dir}/bin/hermes', '--profile', '${wrapper_profile}', *sys.argv[1:]])
        | PY
      require => Exec['install_hermes_agent'],
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
      unless  => "test \"$(git -C ${source_dir} rev-parse HEAD)\" = \"$(cat ${web_revision_file} 2>/dev/null)\" && test -f ${source_dir}/hermes_cli/web_dist/index.html",
      cwd     => "${source_dir}/web",
      path    => ['/bin', '/usr/bin', '/usr/sbin'],
      require => [
        Class['nodejs'],
        Vcsrepo[$source_dir],
      ],
    }
  }
}
