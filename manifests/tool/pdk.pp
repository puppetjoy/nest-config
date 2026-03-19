class nest::tool::pdk {
  if $facts['build'] == 'pdk' {
    $pdk_version        = '3.6.1'
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
    ->
    file_line {
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
    }
  } else {
    case $facts['os']['family'] {
      'Gentoo': {
        file { '/usr/local/bin/pdk':
          mode   => '0755',
          owner  => 'root',
          group  => 'root',
          source => 'puppet:///modules/nest/scripts/pdk.sh',
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
