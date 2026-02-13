class nest::base::wsl {
  if $facts['os']['family'] != 'windows' {
    fail('nest::base::wsl only supports Windows nodes')
  }

  $distribution_name        = 'Nest'
  $image                    = 'registry.gitlab.joyfullee.me/nest/stage1/workstation:latest'
  $reimport_on_image_change = true
  $crane_version            = '0.20.6'
  $crane_source             = "https://github.com/google/go-containerregistry/releases/download/v${crane_version}/go-containerregistry_Windows_x86_64.tar.gz"
  $install_path             = "C:/ProgramData/Nest/wsl/distro/${distribution_name}"
  $image_tar_path           = "C:/ProgramData/Nest/wsl/images/${distribution_name}.tar"
  $image_digest_path        = "C:/ProgramData/Nest/wsl/images/${distribution_name}.digest"

  $wsl_root                 = 'C:/ProgramData/Nest/wsl'
  $cache_dir                = "${wsl_root}/cache"
  $bin_dir                  = "${wsl_root}/bin"
  $crane_archive            = "${cache_dir}/go-containerregistry-${crane_version}.tar.gz"
  $crane_binary             = "${bin_dir}/crane.exe"
  $wsl_binary               = 'C:/Windows/System32/wsl.exe'
  $managed_dirs             = unique([
    'C:/ProgramData/Nest',
    $wsl_root,
    $cache_dir,
    $bin_dir,
    dirname($install_path),
    $install_path,
    dirname($image_tar_path),
    dirname($image_digest_path),
  ])
  $wsl_state                = $facts['wsl'] ? {
    Undef   => {
      'features_enabled' => false,
      'reboot_pending'   => false,
      'ready'            => false,
    },
    default => $facts['wsl'],
  }

  file {
    default:
      ensure => directory,
      owner  => 'Administrators',
      group  => 'None',
    ;
    $managed_dirs:;
  }

  $wsl_feature_unless = "if ((Get-WindowsOptionalFeature -Online -FeatureName 'Microsoft-Windows-Subsystem-Linux').State -eq 'Enabled') { exit 0 } else { exit 1 }"

  exec { 'nest-wsl-enable-subsystem':
    command  => 'Enable-WindowsOptionalFeature -Online -NoRestart -FeatureName Microsoft-Windows-Subsystem-Linux',
    unless   => $wsl_feature_unless,
    provider => powershell,
    returns  => [0, 3010],
    require  => File[$wsl_root],
  }

  $vm_feature_unless = "if ((Get-WindowsOptionalFeature -Online -FeatureName 'VirtualMachinePlatform').State -eq 'Enabled') { exit 0 } else { exit 1 }"

  exec { 'nest-wsl-enable-vm-platform':
    command  => 'Enable-WindowsOptionalFeature -Online -NoRestart -FeatureName VirtualMachinePlatform',
    unless   => $vm_feature_unless,
    provider => powershell,
    returns  => [0, 3010],
    require  => File[$wsl_root],
  }

  $crane_download_command = "Invoke-WebRequest -UseBasicParsing -Uri '${crane_source}' -OutFile '${crane_archive}'"

  exec { 'nest-wsl-download-crane':
    command  => $crane_download_command,
    creates  => $crane_archive,
    provider => powershell,
    require  => File[$cache_dir],
    timeout  => 0,
  }

  exec { 'nest-wsl-install-crane':
    command  => "& 'C:/Windows/System32/tar.exe' -xzf '${crane_archive}' -C '${bin_dir}' 'crane.exe'",
    creates  => $crane_binary,
    provider => powershell,
    require  => [
      File[$bin_dir],
      Exec['nest-wsl-download-crane'],
    ],
  }

  $export_unless = @("END_EXPORT_UNLESS")
    if ((Test-Path '${image_tar_path}') -and
        (Test-Path '${image_digest_path}') -and
        ((Get-Content -Path '${image_digest_path}' -Raw).Trim() -eq (& '${crane_binary}' digest '${image}').Trim())) {
      exit 0
    } else {
      exit 1
    }
    | END_EXPORT_UNLESS

  exec { 'nest-wsl-export-image-rootfs':
    command  => "& '${crane_binary}' export '${image}' '${image_tar_path}'",
    unless   => $export_unless,
    provider => powershell,
    require  => [
      Exec['nest-wsl-enable-subsystem'],
      Exec['nest-wsl-enable-vm-platform'],
      Exec['nest-wsl-install-crane'],
    ],
    timeout  => 0,
  }

  exec { 'nest-wsl-write-image-digest':
    command     => "(& '${crane_binary}' digest '${image}').Trim() | Set-Content -Path '${image_digest_path}' -NoNewline",
    provider    => powershell,
    refreshonly => true,
    subscribe   => Exec['nest-wsl-export-image-rootfs'],
  }

  $distro_exists_unless = "if ((& '${wsl_binary}' --list --quiet | Select-String -Pattern '^${distribution_name}$' -Quiet)) { exit 0 } else { exit 1 }"

  if $wsl_state['ready'] {
    exec { 'nest-wsl-import-distribution-initial':
      command  => "& '${wsl_binary}' --import '${distribution_name}' '${install_path}' '${image_tar_path}' --version 2",
      unless   => $distro_exists_unless,
      provider => powershell,
      require  => Exec['nest-wsl-write-image-digest'],
      timeout  => 0,
    }

    if $reimport_on_image_change {
      $distro_exists_onlyif = $distro_exists_unless

      exec { 'nest-wsl-reimport-distribution':
        command     => "& '${wsl_binary}' --unregister '${distribution_name}'; & '${wsl_binary}' --import '${distribution_name}' '${install_path}' '${image_tar_path}' --version 2",
        onlyif      => $distro_exists_onlyif,
        provider    => powershell,
        refreshonly => true,
        subscribe   => Exec['nest-wsl-write-image-digest'],
        timeout     => 0,
      }
    }
  } elsif $wsl_state['features_enabled'] and $wsl_state['reboot_pending'] {
    notify { 'nest-wsl-reboot-required':
      message => 'WSL features are enabled but pending reboot. Reboot this node and rerun Puppet to continue WSL provisioning.',
    }
  }
}
