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
}
