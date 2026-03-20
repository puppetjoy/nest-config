class nest::tool::pdk {
  $pdk_version               = '3.6.1'
  $pdk_private_ruby_version  = '3.2.8'
  $pdk_bundler_rb            = "/opt/puppetlabs/pdk/private/ruby/${pdk_private_ruby_version}/lib/ruby/gems/3.2.0/gems/pdk-${pdk_version}/lib/pdk/util/bundler.rb"
  $pdk_bundler_command_rb    = "/opt/puppetlabs/pdk/private/ruby/${pdk_private_ruby_version}/lib/ruby/gems/3.2.0/gems/pdk-${pdk_version}/lib/pdk/cli/exec/command.rb"

  if $facts['build'] == 'pdk' {
    $ruby_minor_version = $facts['ruby']['version'].regsubst('^(\d+\.\d+).*', '\1')
    $pdk_gem_dir        = "/usr/local/lib64/ruby/gems/${ruby_minor_version}.0/gems/pdk-${pdk_version}"
    $build_bundler_rb   = "${pdk_gem_dir}/lib/pdk/util/bundler.rb"
    $build_command_rb   = "${pdk_gem_dir}/lib/pdk/cli/exec/command.rb"

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

    # PDK derives its packaged gem path from bundler_basedir/../../.., but
    # our gem-installed layout already puts the active gem root at
    # bundler_basedir. Without this, later PDK file lookups miss their target.
    file_line { 'pdk-gem-path':
      path    => "${pdk_gem_dir}/lib/pdk/util/ruby_version.rb",
      line    => '[bundler_basedir]',
      match   => 'absolute_path.*join.*bundler_basedir',
      require => Package['pdk'];
    }

    nest::tool::pdk::packaged_patch { 'pdk':
      bundler_rb => $build_bundler_rb,
      command_rb => $build_command_rb,
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

        nest::tool::pdk::packaged_patch { 'macos-pdk':
          bundler_rb => $pdk_bundler_rb,
          command_rb => $pdk_bundler_command_rb,
        }
      }
    }
  }
}
