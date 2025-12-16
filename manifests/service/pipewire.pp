class nest::service::pipewire {
  if $facts['profile']['architecture'] in ['arm64', 'riscv'] {
    nest::lib::package_env { 'media-libs/roc-toolkit':
      env    => {
        'EXTRA_ESCONS' => '--libdir=/usr/lib64',
      },
      before => Nest::Lib::Package['media-video/pipewire'],
    }
  }

  # For realtime priority
  # See: https://wiki.gentoo.org/wiki/PipeWire#Audio_Groups
  User <| title == $nest::user |> {
    groups +> 'pipewire',
  }

  if $facts['profile']['variant'] == 'server' {
    $use = ['-X']

    # Work without logind (just a user session)
    User <| title == $nest::user |> {
      groups +> 'audio',
    }

    exec { 'systemd-enable-pipewire-service':
      command => '/bin/systemctl --user --global enable pipewire.service',
      creates => '/etc/systemd/user/default.target.wants/pipewire.service',
    }
  } else {
    $use = []
  }

  nest::lib::package { 'media-video/pipewire':
    ensure => installed,
    use    => $use + ['roc', 'sound-server'],
  }
  ->
  exec {
    'systemd-enable-pipewire':
      command => '/bin/systemctl --user --global enable pipewire.socket',
      creates => '/etc/systemd/user/sockets.target.wants/pipewire.socket',
    ;

    'systemd-enable-pipewire-pulse':
      command => '/bin/systemctl --user --global enable pipewire-pulse.socket',
      creates => '/etc/systemd/user/sockets.target.wants/pipewire-pulse.socket',
    ;

    'systemd-enable-wireplumber':
      command => '/bin/systemctl --user --global enable wireplumber.service',
      creates => '/etc/systemd/user/pipewire.service.wants/wireplumber.service',
    ;
  }

  # For increasing pipewire scheduling priority
  nest::lib::package { 'sys-auth/rtkit':
    ensure => installed,
  }

  # Fix stuttering audio in VMware
  # See: https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/469
  if $facts['profile']['platform'] and $facts['profile']['platform'] =~ /^vmware/ {
    file {
      default:
        mode    => '0644',
        owner   => 'root',
        group   => 'root',
        require => Package['media-video/pipewire'],
      ;

      '/etc/pipewire':
        ensure  => directory,
      ;

      '/etc/pipewire/pipewire.conf':
        replace => false,
        source  => '/usr/share/pipewire/pipewire.conf',
      ;
    }
    ->
    file_line { 'pipewire-default-clock-rate':
      path  => '/etc/pipewire/pipewire.conf',
      line  => '    default.clock.rate           = 44100',
      match => '^\s*#?default\.clock\.rate\s*=',
    }
  }
}
