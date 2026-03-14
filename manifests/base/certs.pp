class nest::base::certs {
  case $facts['os']['family'] {
    'Gentoo': {
      # See: https://wiki.gentoo.org/wiki/Certificates
      file { [
        '/usr/local/share',
        '/usr/local/share/ca-certificates',
      ]:
        ensure => directory,
        mode   => '0755',
        owner  => 'root',
        group  => 'root',
      }

      file { '/usr/local/share/ca-certificates/eyrie.crt':
        mode   => '0644',
        owner  => 'root',
        group  => 'root',
        source => 'puppet:///modules/nest/certs/eyrie.crt',
      }
      ~>
      exec { 'update-ca-certificates':
        command     => '/usr/sbin/update-ca-certificates',
        refreshonly => true,
      }
    }

    'Darwin': {
      $eyrie_crt         = '/etc/ssl/certs/eyrie.crt'
      $eyrie_fingerprint = '32C34D755F5206B7B2A96E21697F42BE698AD7BE'

      file { $eyrie_crt:
        mode   => '0644',
        owner  => 'root',
        group  => 'wheel',
        source => 'puppet:///modules/nest/certs/eyrie.crt',
      }

      exec { 'security-add-trusted-cert-eyrie-root':
        command => shellquote(
          '/usr/bin/security',
          'add-trusted-cert',
          '-d',
          '-r',
          'trustRoot',
          '-k',
          '/Library/Keychains/System.keychain',
          $eyrie_crt
        ),
        unless  => "/usr/bin/security find-certificate -a -Z -c Eyrie /Library/Keychains/System.keychain | /usr/bin/grep -q '${eyrie_fingerprint}'",
        require => File[$eyrie_crt],
      }
    }

    'windows': {
      $eyrie_crt = 'C:/tools/cygwin/etc/pki/ca-trust/source/anchors/eyrie.crt'

      file { $eyrie_crt:
        mode   => '0644',
        owner  => 'Administrators',
        group  => 'None',
        source => 'puppet:///modules/nest/certs/eyrie.crt',
      }
      ~>
      exec { 'update-ca-trust':
        command     => shellquote(
          'C:/tools/cygwin/bin/bash.exe', '-c',
          'source /etc/profile && /usr/bin/update-ca-trust'
        ),
        refreshonly => true,
      }

      exec { 'certutil-addstore-eyrie-root':
        command  => "C:/Windows/System32/certutil.exe -addstore Root ${eyrie_crt}",
        unless   => "if ((C:/Windows/System32/certutil.exe -verify ${eyrie_crt} | Select-String -Pattern UNTRUSTED).Length -gt 0) { exit 1 }",
        require  => File['C:/tools/cygwin/etc/pki/ca-trust/source/anchors/eyrie.crt'],
        provider => powershell,
      }
    }
  }
}
