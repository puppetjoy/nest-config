class nest::service::power (
  Optional[Enum['performance', 'balanced', 'powersaver']] $profile = undef,
) {
  require 'nest::gui::policykit'

  nest::lib::package { 'sys-power/power-profiles-daemon':
    ensure => installed,
  }

  if $profile {
    # Map our logical profiles to power-profiles-daemon names
    $profile_map = {
      'performance' => 'performance',
      'balanced'    => 'balanced',
      'powersaver'  => 'power-saver',
    }

    $service_profile = $profile_map[$profile]

    systemd::manage_unit { 'power-profile.service':
      ensure        => 'present',
      unit_entry    => {
        'Description' => 'Set power profile',
        'After'       => 'multi-user.target',
      },
      service_entry => {
        'Type'            => 'oneshot',
        'ExecStart'       => "/usr/bin/powerprofilesctl set ${service_profile}",
        'RemainAfterExit' => true,
      },
      install_entry => {
        'WantedBy' => 'multi-user.target',
      },
      enable        => true,
    }
  } else {
    systemd::manage_unit { 'power-profile.service':
      ensure => 'absent',
      enable => false,
    }
  }
}
