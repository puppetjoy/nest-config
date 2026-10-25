class nest::base::cli {
  nest::lib::package { 'app-admin/nest-cli':
    # Immutable capacity/transaction/reboot source; retain the activation-safe rollback floor.
    ensure => '0.9.0_p20261021-r6',
    tag    => 'nest_cli_package',
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
      tag     => 'dns_failover',
    ;

    '/etc/nest/reset-test-filter.rules':
      source => 'puppet:///modules/nest/cli/reset-test-filter.rules',
    ;

    '/usr/libexec/nest':
      ensure => directory,
      mode   => '0755',
    ;

    '/usr/libexec/nest/transfer-generation.py':
      source => 'puppet:///modules/nest/cli/transfer-generation.py',
    ;

    '/usr/libexec/nest/check-stage3-root.py':
      source => 'puppet:///modules/nest/build/check-stage3-root.py',
    ;
  }
}
