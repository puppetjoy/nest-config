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

  systemd::manage_unit { 'falcon-arc-first-fault.service':
    unit_entry    => {
      'Description'         => 'Preserve the first uncorrected Arc PCIe error and PM prehistory',
      'After'               => 'sys-kernel-tracing.mount',
      'RequiresMountsFor'   => '/sys/kernel/tracing',
      'ConditionPathExists' => '/sys/bus/pci/devices/0000:05:00.0',
    },
    service_entry => {
      'Type'                     => 'oneshot',
      'RemainAfterExit'          => true,
      'ExecStart'                => '/usr/bin/python3 /usr/local/sbin/falcon-arc-first-fault',
      'TimeoutStartSec'          => '15s',
      'RuntimeDirectory'         => 'falcon-arc-first-fault',
      'RuntimeDirectoryMode'     => '0700',
      'RuntimeDirectoryPreserve' => 'yes',
      'ProtectHome'              => true,
      'ProtectSystem'            => 'strict',
      'PrivateNetwork'           => true,
    },
    install_entry => { 'WantedBy' => 'multi-user.target' },
  }

  # Stop/restart must not clear the trace or rearm a consumed first-error trigger.
  service { 'falcon-arc-first-fault':
    ensure  => running,
    enable  => true,
    require => [File['/usr/local/sbin/falcon-arc-first-fault'], Systemd::Manage_unit['falcon-arc-first-fault.service']],
  }
}
