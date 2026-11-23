# Temporary passive diagnosis for endpoint loss; not a GPU power workaround.
# Remove after actionable first-error evidence and the accepted causal repair.
class nest::host::falcon::arc_diagnostics {
  tag 'falcon_arc_diagnostics'

  file { '/usr/local/sbin/falcon-arc-first-fault':
    ensure => file,
    owner  => 'root',
    group  => 'root',
    mode   => '0755',
    source => 'puppet:///modules/nest/host/falcon/arc-first-fault.py',
  }

  # Use the module's full-unit API: its typed map lacks preservation/sandbox keys.
  # Stop/restart must not clear the trace or rearm a consumed first-error trigger.
  systemd::unit_file { 'falcon-arc-first-fault.service':
    source  => 'puppet:///modules/nest/host/falcon/falcon-arc-first-fault.service',
    active  => true,
    enable  => true,
    require => File['/usr/local/sbin/falcon-arc-first-fault'],
  }
}
