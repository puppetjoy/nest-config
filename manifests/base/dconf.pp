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
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    [
      '/etc/dconf',
      '/etc/dconf/db',
      '/etc/dconf/profile',
    ]:
      ensure => directory,
    ;

    [
      '/etc/dconf/db/local.d',
      '/etc/dconf/db/local.d/locks',
    ]:
      ensure  => directory,
      purge   => true,
      recurse => true,
      force   => true,
    ;

    '/etc/dconf/profile/user':
      mode    => '0644',
      content => $user_profile_content,
      notify  => Exec['dconf-update'],
    ;
  }
}
