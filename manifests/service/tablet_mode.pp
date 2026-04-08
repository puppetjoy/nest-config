class nest::service::tablet_mode {
  include 'nest' # for nest::user

  file {
    '/usr/local/bin/nest-gnome-tablet-session-mode':
      ensure => file,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
      source => 'puppet:///modules/nest/tablet-mode/nest-gnome-tablet-session-mode',
    ;

    '/usr/local/bin/nest-tablet-mode-monitor':
      ensure => file,
      mode   => '0755',
      owner  => 'root',
      group  => 'root',
      source => 'puppet:///modules/nest/tablet-mode/nest-tablet-mode-monitor',
    ;

    '/etc/systemd/system/nest-tablet-mode.service':
      ensure  => file,
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => @("END"),
        [Unit]
        Description=Sync tablet mode hardware state with GNOME sessions
        After=systemd-user-sessions.service

        [Service]
        Type=simple
        ExecStart=/usr/local/bin/nest-tablet-mode-monitor ${nest::user}
        Restart=on-failure
        RestartSec=5

        [Install]
        WantedBy=multi-user.target
        | END
      notify  => Nest::Lib::Systemd_reload['tablet-mode'],
    ;
  }

  nest::lib::systemd_reload { 'tablet-mode': }

  service { 'nest-tablet-mode':
    enable    => true,
    require   => File['/etc/systemd/system/nest-tablet-mode.service'],
    subscribe => [
      File['/etc/systemd/system/nest-tablet-mode.service'],
      File['/usr/local/bin/nest-gnome-tablet-session-mode'],
      File['/usr/local/bin/nest-tablet-mode-monitor'],
    ],
  }
}
