class nest::base::mta::postfix (
  Enum['present', 'absent'] $ensure,
) {
  define map (
    String $content,
    String $mode = '0644',
  ) {
    file { "/etc/postfix/${name}":
      mode    => $mode,
      owner   => 'root',
      group   => 'root',
      content => $content,
    }
    ~>
    exec { "/usr/sbin/postmap /etc/postfix/${name}":
      refreshonly => true,
    }
  }

  define setting (
    Optional[String] $value = undef,
  ) {
    if $value {
      exec { "postconf-set-${name}":
        command => "/usr/sbin/postconf ${name.shellquote}=${value.shellquote}",
        unless  => "/usr/bin/test \"`/usr/sbin/postconf -h ${name.shellquote}`\" = ${value.shellquote}",
      }
    } else {
      exec { "postconf-unset-${name}":
        command => "/usr/sbin/postconf -X ${name.shellquote}",
        unless  => "/usr/bin/test -z \"`/usr/sbin/postconf -n ${name.shellquote}`\"",
      }
    }
  }

  case $ensure {
    'present': {
      if $nest::gmail_username and $nest::gmail_password {
        $relayhost                  = '[smtp-relay.gmail.com]:587'
        $saslpass                   = "[smtp-relay.gmail.com]:587 ${nest::gmail_username}:${nest::gmail_password}\n"
        $smtp_sasl_auth_enable      = 'yes'
        $smtp_sasl_password_maps    = 'hash:/etc/postfix/saslpass'
        $smtp_sasl_security_options = 'noanonymous'
        $smtp_tls_cafile            = '/etc/ssl/certs/ca-certificates.crt'
        $smtp_tls_security_level    = 'may'
      } else {
        $relayhost = '[smtp.nest]'
        $saslpass  = ''
      }

      nest::lib::package { 'mail-mta/postfix':
        ensure => installed,
        use    => 'sasl',
      }
      ~>
      exec { '/usr/bin/newaliases':
        refreshonly => true,
      }
      ->
      nest::base::mta::postfix::map {
        'saslpass':
          mode    => '0600',
          content => $saslpass,
        ;

        'virtual':
          content => "@${trusted['certname']}.nest nest@joyfullee.me\n",
        ;
      }
      ->
      nest::base::mta::postfix::setting {
        'compatibility_level':
          value => '2',
        ;

        'mydomain':
          value => 'nest',
        ;

        'mynetworks_style':
          value => 'subnet',
        ;

        'relayhost':
          value => $relayhost,
        ;

        'smtp_sasl_auth_enable':
          value => $smtp_sasl_auth_enable,
        ;

        'smtp_sasl_password_maps':
          value => $smtp_sasl_password_maps,
        ;

        'smtp_sasl_security_options':
          value => $smtp_sasl_security_options,
        ;

        'smtp_tls_security_level':
          value => $smtp_tls_security_level,
        ;

        'smtp_tls_CAfile':
          value => $smtp_tls_cafile,
        ;

        'virtual_alias_maps':
          value => 'hash:/etc/postfix/virtual'
        ;
      }
      ~>
      service { 'postfix':
        enable => true,
      }
    }

    'absent': {
      service { 'postfix':
        ensure => stopped,
        enable => false,
      }
      ->
      file { '/etc/postfix':
        ensure => absent,
        force  => true,
      }
      ->
      nest::lib::package { 'mail-mta/postfix':
        ensure => absent,
      }
    }
  }
}
