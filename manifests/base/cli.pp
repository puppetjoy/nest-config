class nest::base::cli {
  nest::lib::package { 'app-admin/nest-cli':
    ensure => latest,
  }

  file {
    default:
      mode  => '0644',
      owner => 'root',
      group => 'root',
    ;

    '/etc/nest':
      ensure => directory,
    ;

    '/etc/nest/reset-filter.rules':
      content => epp('nest/cli/reset-filter.rules.epp', { 'rules' => $nest::reset_filter_rules }),
    ;

    '/etc/nest/reset-test-filter.rules':
      source => 'puppet:///modules/nest/cli/reset-test-filter.rules',
    ;
  }

  # Required for building live ISOs
  # Do not use nest::lib::package so grub class can define USE flags
  package { 'sys-boot/grub':
    ensure => installed,
  }

  # Fix broken argument processing with grub-mkrescue(1)
  # See: https://gitlab.joyfullee.me/nest/cli/-/issues/26
  file { '/usr/local/bin/xorriso':
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => "#!/bin/zsh\nexec /usr/bin/xorriso \"\${@:#--}\"\n",
  }
}
