class nest::tool::bolt (
  String            $cert,
  Sensitive[String] $key,
  Optional[String]  $ca = undef,
) {
  if $facts['build'] == 'bolt' {
    $bolt_version       = '4.0.0'
    $ruby_minor_version = $facts['ruby']['version'].regsubst('^(\d+\.\d+).*', '\1')
    $bolt_gem_dir       = "/usr/local/lib64/ruby/gems/${ruby_minor_version}.0/gems/bolt-${bolt_version}"

    package {
      default:
        install_options => ['--bindir', '/usr/local/bin'],
        provider        => gem,
      ;
      ['ed25519', 'bcrypt_pbkdf', 'toml-rb']:
        ensure => installed,
      ;
      'bolt':
        ensure => $bolt_version,
      ;
    }
    ->
    file {
      '/usr/local/bin':
        purge   => true,
        recurse => true;
      '/usr/local/bin/bolt':
        ensure => file;
    }

    # For vaultwarden token hashing
    nest::lib::package { 'app-crypt/argon2':
      ensure => installed,
    }

    # Fix podman json parsing
    # Bolt expects pretty json that podman no longer provides
    # Revert to inherited docker parsing function
    exec { 'bolt-fix-podman-transport':
      command => "/bin/sed -i '/^\\s*private def extract_json/,/^\\s*end/d' ${bolt_gem_dir}/lib/bolt/transport/podman/connection.rb",
      onlyif  => "/bin/grep -q '^\\s*private def extract_json' ${bolt_gem_dir}/lib/bolt/transport/podman/connection.rb",
      require => Package['bolt'],
    }
  } else {
    require nest::base::puppet

    if $ca {
      $ca_content = $ca
    } elsif $settings::ssldir == '/etc/puppetlabs/puppet/ssl' {
      $ca_content = file('/etc/puppetlabs/puppet/ssl/certs/ca.pem')
    } else {
      $ca_content = ''
    }

    $config_group = $facts['os']['family'] ? {
      'Darwin' => 'wheel',
      default  => 'root',
    }

    file {
      default:
        mode  => '0644',
        owner => 'root',
        group => $config_group,
      ;

      '/etc/puppetlabs/bolt':
        ensure => directory,
      ;

      '/etc/puppetlabs/bolt/ca.pem':
        content => $ca_content,
      ;

      '/etc/puppetlabs/bolt/cert.pem':
        content => $cert,
      ;

      '/etc/puppetlabs/bolt/key.pem':
        content   => $key,
        show_diff => false,
      ;

      '/etc/puppetlabs/bolt/bolt-defaults.yaml':
        content   => epp('nest/puppet/bolt-defaults.yaml.epp', {
          puppetdb_server_url => 'https://puppetdb.nest:8081',
          puppetdb_cacert     => '/etc/puppetlabs/bolt/ca.pem',
          puppetdb_cert       => '/etc/puppetlabs/bolt/cert.pem',
          puppetdb_key        => '/etc/puppetlabs/bolt/key.pem',
        }),
      ;
    }

    case $facts['os']['family'] {
      'Gentoo': {
        file { '/usr/local/bin/bolt':
          mode    => '0755',
          content => epp('nest/scripts/bolt.sh.epp', {
            'puppetcore_gem_source' => $nest::base::puppet::puppetcore_gem_source,
          }),
        }
      }

      'Darwin': {
        package { 'openvox8-openbolt':
          ensure  => installed,
          require => Class['nest::base::puppet'],
        }
      }
    }
  }
}
