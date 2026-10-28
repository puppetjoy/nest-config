class nest::app::hermes::extracted_plugins {
  $install_dir = $nest::app::hermes::install_dir
  $patch_dir   = "${install_dir}/plugin-patches"
  $patches     = ['honcho', 'camofox', 'github-copilot']
  $inputs      = $patches.map |String $name| { file("nest/app/hermes/extracted-plugins/${name}.patch") }
  $patch_content = join($inputs, '\n')
  $stage_script  = file('nest/app/hermes/stage-extracted-plugins.py')
  $revision      = sha256("${patch_content}\n${stage_script}")
  $asset_dir   = "${install_dir}/plugin-assets-${revision}"

  file { $patch_dir:
    ensure  => directory,
    mode    => '0755',
    require => File[$install_dir],
  }

  $patches.each |String $name| {
    file { "${patch_dir}/${name}.patch":
      ensure  => file,
      source  => "puppet:///modules/nest/app/hermes/extracted-plugins/${name}.patch",
      mode    => '0644',
      require => File[$patch_dir],
    }
  }

  file { "${install_dir}/bin/stage-extracted-plugins":
    ensure  => file,
    source  => 'puppet:///modules/nest/app/hermes/stage-extracted-plugins.py',
    mode    => '0755',
    require => File["${install_dir}/bin"],
  }

  exec { 'stage_hermes_extracted_plugins':
    command => "/usr/bin/python3.14 ${install_dir}/bin/stage-extracted-plugins ${asset_dir} --patches ${patch_dir}",
    creates => "${asset_dir}/sources.json",
    path    => ['/bin', '/usr/bin', '/usr/sbin'],
    timeout => 1800,
    require => [
      Package['dev-lang/python:3.14'],
      Class['nest::base::git'],
      File["${install_dir}/bin/stage-extracted-plugins"],
      $patches.map |String $name| { File["${patch_dir}/${name}.patch"] },
    ],
  }

  file { "${install_dir}/extracted-plugins":
    ensure  => link,
    target  => $asset_dir,
    require => Exec['stage_hermes_extracted_plugins'],
  }
}
