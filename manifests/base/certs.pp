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
      $cert_file   = '/etc/ssl/certs/eyrie.crt'
      $cert_source = find_file('nest/certs/eyrie.crt')
      $cert_info = generate(
        '/usr/bin/openssl',
        'x509',
        '-in',
        $cert_source,
        '-noout',
        '-subject',
        '-nameopt',
        'RFC2253',
        '-fingerprint',
        '-sha1',
      ).chomp.split("\n")
      $cert_subject_line     = $cert_info[0]
      $cert_fingerprint_line = $cert_info[1]
      $cert_cn               = regsubst($cert_subject_line, '^subject=.*CN=([^,]+).*$' , '\1')
      $cert_fingerprint_hex  = regsubst($cert_fingerprint_line, '^.*=', '')
      $cert_fingerprint      = regsubst($cert_fingerprint_hex, ':', '', 'G')

      file { $cert_file:
        mode   => '0644',
        owner  => 'root',
        group  => 'wheel',
        source => 'puppet:///modules/nest/certs/eyrie.crt',
      }

      exec { 'security-add-trusted-cert-root':
        command => shellquote(
          '/usr/bin/security',
          'add-trusted-cert',
          '-d',
          '-r',
          'trustRoot',
          '-k',
          '/Library/Keychains/System.keychain',
          $cert_file
        ),
        unless  => "/usr/bin/security find-certificate -a -Z -c ${cert_cn.shellquote} /Library/Keychains/System.keychain | /usr/bin/grep -q '${cert_fingerprint}'",
        require => File[$cert_file],
      }
    }

    'windows': {
      $cert_file = 'C:/tools/cygwin/etc/pki/ca-trust/source/anchors/eyrie.crt'

      file { $cert_file:
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

      exec { 'certutil-addstore-root':
        command  => "C:/Windows/System32/certutil.exe -addstore Root ${cert_file}",
        unless   => "if ((C:/Windows/System32/certutil.exe -verify ${cert_file} | Select-String -Pattern UNTRUSTED).Length -gt 0) { exit 1 }",
        require  => File[$cert_file],
        provider => powershell,
      }
    }
  }
}
