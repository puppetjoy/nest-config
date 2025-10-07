class nest::base::eyaml {
  case $facts['os']['family'] {
    'Gentoo': {
      $conf_dir = '/etc/eyaml'

      nest::lib::package { 'dev-ruby/hiera-eyaml':
        ensure => installed,
        before => File[$conf_dir],
      }

      File {
        mode  => '0644',
        owner => 'root',
        group => 'root',
      }

      if $nest::eyaml_private_key {
        $eyaml_private_key = $nest::eyaml_private_key

        exec { 'make-eyaml-key-readable':
          command => "/usr/sbin/setfacl -m user:${nest::user}:r /etc/eyaml/keys/private_key.pkcs7.pem",
          unless  => "/usr/sbin/getfacl /etc/eyaml/keys/private_key.pkcs7.pem | /bin/grep '^user:${nest::user}:r--'",
          require => [
            File['/etc/eyaml/keys/private_key.pkcs7.pem'],
            User[$nest::user],
          ],
        }
      } else {
        $eyaml_private_key = ''
      }
    }

    'windows': {
      $conf_dir = 'C:/tools/cygwin/etc/eyaml'

      exec { 'gem-install-hiera-eyaml':
        command     => shellquote(
          'C:/tools/cygwin/bin/bash.exe', '-c',
          '/usr/bin/gem install hiera-eyaml'
        ),
        environment => "HOME=/home/${nest::user}",
        creates     => "C:/tools/cygwin/home/${nest::user}/bin/eyaml",
        require     => Package['ruby'],
        before      => File[$conf_dir],
      }

      File {
        mode  => '0644',
        owner => 'Administrators',
        group => 'None',
      }

      $eyaml_private_key = $nest::eyaml_private_key
    }
  }

  $eyaml_conf = @(CONF)
    ---
    pkcs7_private_key: '/etc/eyaml/keys/private_key.pkcs7.pem'
    pkcs7_public_key: '/etc/eyaml/keys/public_key.pkcs7.pem'
    | CONF

  file {
    [$conf_dir, "${conf_dir}/keys"]:
      ensure => directory,
    ;

    "${conf_dir}/config.yaml":
      content => $eyaml_conf,
    ;

    "${conf_dir}/keys/public_key.pkcs7.pem":
      content => $nest::eyaml_public_key,
    ;

    "${conf_dir}/keys/private_key.pkcs7.pem":
      mode    => '0640',
      content => $eyaml_private_key,
    ;
  }
}
