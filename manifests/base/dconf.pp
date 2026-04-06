class nest::base::dconf {
  $user_profile_content = @("END")
    user-db:user
    system-db:local
    | END

  exec { 'dconf-update':
    command     => '/usr/bin/dconf update',
    refreshonly => true,
  }

  file {
    default:
      owner => 'root',
      group => 'root',
    ;

    '/etc/dconf':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/db':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/db/local.d':
      ensure  => directory,
      mode    => '0755',
      purge   => true,
      recurse => true,
      force   => true,
    ;

    '/etc/dconf/db/local.d/locks':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/profile':
      ensure => directory,
      mode   => '0755',
    ;

    '/etc/dconf/profile/user':
      mode    => '0644',
      content => $user_profile_content,
      notify  => Exec['dconf-update'],
    ;
  }
}
