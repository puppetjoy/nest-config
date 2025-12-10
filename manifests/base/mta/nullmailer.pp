class nest::base::mta::nullmailer (
  Enum['present', 'absent'] $ensure,
) {
  case $ensure {
    'present': {
      if $nest::gmail_username and $nest::gmail_password {
        $remotes_content = "smtp-relay.gmail.com smtp --user=${nest::gmail_username} --pass=${nest::gmail_password} --port=587 --starttls\n"
      } else {
        $remotes_content = "smtp.nest\n"
      }

      nest::lib::package { 'mail-mta/nullmailer':
        ensure => installed,
      }
      ->
      file {
        default:
          mode  => '0644',
          owner => 'root',
          group => 'root',
        ;

        '/etc/nullmailer/adminaddr':
          content => "nest@joyfullee.me\n",
        ;

        '/etc/nullmailer/defaultdomain':
          content => "nest\n",
        ;

        '/etc/nullmailer/me':
          content => "${trusted['certname']}.nest\n",
        ;

        '/etc/nullmailer/remotes':
          mode      => '0640',
          group     => 'nullmail',
          content   => $remotes_content,
          show_diff => false,
        ;
      }
      ~>
      service { 'nullmailer':
        enable => !$facts['live'], # doesn't start on NFS root
        tag    => 'boot',
      }

      # XXX cleanup
      nest::lib::package { 'net-mail/mailbase':
        ensure => absent,
      }

      file { '/etc/mail':
        ensure => absent,
        force  => true,
      }
    }

    'absent': {
      service { 'nullmailer':
        ensure => stopped,
        enable => false,
      }
      ->
      file { '/etc/nullmailer':
        ensure => absent,
        force  => true,
      }
      ->
      nest::lib::package { 'mail-mta/nullmailer':
        ensure => absent,
      }
    }
  }
}
