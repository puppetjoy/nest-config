class nest::tool::pdk {
  $pdk_version               = '3.6.1'
  $pdk_private_ruby_version  = '3.2.8'
  $pdk_bundler_command_rb    = "/opt/puppetlabs/pdk/private/ruby/${pdk_private_ruby_version}/lib/ruby/gems/3.2.0/gems/pdk-${pdk_version}/lib/pdk/cli/exec/command.rb"

  if $facts['build'] == 'pdk' {
    $ruby_minor_version = $facts['ruby']['version'].regsubst('^(\d+\.\d+).*', '\1')
    $pdk_gem_dir        = "/usr/local/lib64/ruby/gems/${ruby_minor_version}.0/gems/pdk-${pdk_version}"

    package { 'pdk':
      ensure          => $pdk_version,
      install_options => ['--bindir', '/usr/local/bin'],
      provider        => gem,
    }
    ->
    file {
      '/usr/local/bin':
        purge   => true,
        recurse => true;
      '/usr/local/bin/pdk':
        ensure => file;
    }

    file_line {
      default:
        require => Package['pdk'];

      # PDK derives its packaged gem path from bundler_basedir/../../.., but
      # our gem-installed layout already puts the active gem root at
      # bundler_basedir. Without this, later PDK file lookups miss their target.
      'pdk-gem-path':
        path  => "${pdk_gem_dir}/lib/pdk/util/ruby_version.rb",
        line  => '[bundler_basedir]',
        match => 'absolute_path.*join.*bundler_basedir',
      ;

      # PDK assumes its initial lock refresh can stay local because packaged
      # installs should already have everything cached. That assumption breaks in
      # this image, so allow the bootstrap json refresh to resolve remotely.
      'pdk-bundler-install-remote':
        path  => "${pdk_gem_dir}/lib/pdk/util/bundler.rb",
        line  => 'update_lock!(only: { json: nil }, local: false)',
        match => 'update_lock.*json.*local',
      ;

      # PDK later re-runs bundle lock --update --local during ensure_bundle!.
      # That can fail even after bundle install has already fetched the needed
      # gems, so force this lock refresh to resolve remotely as well.
      'pdk-bundler-update-lock-remote':
        path  => "${pdk_gem_dir}/lib/pdk/util/bundler.rb",
        line  => '        bundle.update_lock!(with: gem_overrides, local: false)',
        match => 'bundle\.update_lock!\(with: gem_overrides, local: all_deps_available\)',
      ;

      # PDK clears the environment before exec'ing Bundler. Preserve Bundler's
      # authenticated source variables first so private gem sources still work.
      'pdk-bundler-source-env':
        path  => "${pdk_gem_dir}/lib/pdk/cli/exec/command.rb",
        line  => "          bundler_source_env = ENV.select { |name, _value| name.start_with?('BUNDLE_RUBYGEMS_') }",
        match => '# Bundler 2\.1\.0 or greater',
      ;

      # Restore those authenticated source variables inside with_unbundled_env so
      # Bundler can still reach rubygems-puppetcore after PDK sanitizes ENV.
      'pdk-restore-bundler-unbundled-env':
        path               => "${pdk_gem_dir}/lib/pdk/cli/exec/command.rb",
        line               => '            bundler_source_env.each { |name, value| ENV[name] = value }',
        after              => '::Bundler\.with_unbundled_env do',
        append_on_no_match => false,
      ;
    }
  } else {
    require nest::base::puppet

    case $facts['os']['family'] {
      'Gentoo': {
        file { '/usr/local/bin/pdk':
          mode    => '0755',
          owner   => 'root',
          group   => 'root',
          content => epp('nest/scripts/pdk.sh.epp', {
            'puppetcore_gem_source' => $nest::base::puppet::puppetcore_gem_source,
          }),
        }
      }

      'Darwin': {
        homebrew::tap { 'nest/tap':
          source => 'https://gitlab.joyfullee.me/nest/tap.git',
        }
        ->
        package { 'pdk':
          ensure  => installed,
          require => Class['nest::base::puppet'], # for puppetcore profile
        }

        file_line {
          default:
            require => Package['pdk'];

          # PDK clears the environment before exec'ing Bundler. Preserve Bundler's
          # authenticated source variables first so private gem sources still work.
          'macos-pdk-bundler-source-env':
            path  => $pdk_bundler_command_rb,
            line  => "          bundler_source_env = ENV.select { |name, _value| name.start_with?('BUNDLE_RUBYGEMS_') }",
            match => '# Bundler 2\.1\.0 or greater',
          ;

          # Restore those authenticated source variables inside with_unbundled_env so
          # Bundler can still reach rubygems-puppetcore after PDK sanitizes ENV.
          'macos-pdk-restore-bundler-unbundled-env':
            path               => $pdk_bundler_command_rb,
            line               => '            bundler_source_env.each { |name, value| ENV[name] = value }',
            after              => '::Bundler\.with_unbundled_env do',
            append_on_no_match => false,
          ;
        }
      }
    }
  }
}
