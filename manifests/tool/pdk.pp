class nest::tool::pdk {
  if $facts['build'] == 'pdk' {
    $pdk_version        = '3.6.1'
    $bolt_version       = '5.0.1'
    $ruby_minor_version = $facts['ruby']['version'].regsubst('^(\d+\.\d+).*', '\1')
    $pdk_gem_dir        = "/usr/local/lib64/ruby/gems/${ruby_minor_version}.0/gems/pdk-${pdk_version}"

    package {
      default:
        install_options => ['--bindir', '/usr/local/bin'],
        provider        => gem;

      'pdk':
        ensure => $pdk_version;

      # Puppet 8 validation now expects Bolt in the local gem set
      'bolt':
        ensure => $bolt_version;
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

      # The default path is bundler_basedir/../../.. which doesn't work
      'pdk-gem-path':
        path  => "${pdk_gem_dir}/lib/pdk/util/ruby_version.rb",
        line  => '[bundler_basedir]',
        match => 'absolute_path.*join.*bundler_basedir',
      ;

      # Yes, install missing gems into the container image
      'pdk-bundler-install-remote':
        path  => "${pdk_gem_dir}/lib/pdk/util/bundler.rb",
        line  => 'update_lock!(only: { json: nil }, local: false)',
        match => 'update_lock.*json.*local',
      ;

      # Keep Bundler source credentials before with_unbundled_env clears them
      'pdk-bundler-source-env':
        path  => "${pdk_gem_dir}/lib/pdk/cli/exec/command.rb",
        line  => "          bundler_source_env = ENV.select { |name, _value| name.start_with?('BUNDLE_RUBYGEMS_') }",
        match => '# Bundler 2\.1\.0 or greater',
      ;

      # Restore Bundler source credentials inside the unbundled_env block
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
        homebrew::tap { 'puppetlabs/puppet': }
        ->
        package { 'pdk':
          ensure => installed,
        }
      }
    }
  }
}
