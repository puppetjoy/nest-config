define nest::tool::pdk::packaged_patch (
  String $bundler_rb,
  String $command_rb,
) {
  File_line {
    require => Package['pdk'],
  }

  # PDK assumes its initial lock refresh can stay local because packaged
  # installs should already have everything cached. That assumption breaks
  # once the active cache drifts ahead of the packaged bundle.
  file_line { "${title}-bundler-install-remote":
    path  => $bundler_rb,
    line  => 'update_lock!(only: { json: nil }, local: false)',
    match => 'update_lock.*json.*local',
  }

  # PDK later re-runs bundle lock --update --local during ensure_bundle!.
  # That can fail even after bundle check succeeds, so force this lock
  # refresh to resolve remotely as well.
  file_line { "${title}-bundler-update-lock-remote":
    path  => $bundler_rb,
    line  => '        bundle.update_lock!(with: gem_overrides, local: false)',
    match => 'bundle\.update_lock!\(with: gem_overrides, local: all_deps_available\)',
  }

  # PDK clears the environment before exec'ing Bundler. Preserve Bundler's
  # authenticated source variables first so private gem sources still work.
  file_line { "${title}-bundler-source-env":
    path  => $command_rb,
    line  => "          bundler_source_env = ENV.select { |name, _value| name.start_with?('BUNDLE_RUBYGEMS_') }",
    match => '# Bundler 2\.1\.0 or greater',
  }

  # Restore those authenticated source variables inside with_unbundled_env so
  # Bundler can still reach rubygems-puppetcore after PDK sanitizes ENV.
  file_line { "${title}-restore-bundler-unbundled-env":
    path               => $command_rb,
    line               => '            bundler_source_env.each { |name, value| ENV[name] = value }',
    after              => '::Bundler\.with_unbundled_env do',
    append_on_no_match => false,
  }
}
