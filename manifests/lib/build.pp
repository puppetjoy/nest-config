define nest::lib::build (
  String                                   $args      = '', # lint:ignore:params_empty_string_assignment
  Optional[Variant[String, Array[String]]] $command   = undef,
  Optional[String]                         $defconfig = undef,
  String                                   $dir       = $name,
  Boolean                                  $distcc    = true,
  Boolean                                  $llvm      = false,
  String                                   $makeargs  = '', # lint:ignore:params_empty_string_assignment
) {
  if $llvm {
    $base_path = "${dirname($facts['llvm_clang'])}:/usr/bin:/bin"
    $makeargs_real = "LLVM=1 ${makeargs}"
  } else {
    $base_path = '/usr/bin:/bin'
    $makeargs_real = $makeargs
  }

  if $distcc {
    $path = "/usr/lib/distcc/bin:${base_path}"
  } else {
    $path = $base_path
  }

  if $command {
    $command_joined = [$command].flatten.join(' && ')
    $build_command  = "(${command_joined})"
  } else {
    include 'nest::base::portage'
    $build_command = "make ${nest::base::portage::makeopts} ${makeargs_real} ${args}"
  }

  if $defconfig {
    file { "${dir}/.defconfig":
      mode    => '0644',
      owner   => 'root',
      group   => 'root',
      content => "${defconfig}\n",
    }
    ~>
    exec { "${name}-reset-config":
      command     => "/bin/rm -f ${dir}/.config",
      refreshonly => true,
    }
    ->
    exec { "${name}-defconfig":
      command => "/usr/bin/make ${makeargs_real} ${defconfig}",
      cwd     => $dir,
      creates => "${dir}/.config",
      path    => $path,
      notify  => Exec["${name}-build"],
    }
    ->
    Nest::Lib::Kconfig <| config == "${dir}/.config" |>
    ~>
    exec { "${name}-olddefconfig":
      command     => "/usr/bin/make ${makeargs_real} olddefconfig",
      cwd         => $dir,
      refreshonly => true,
      path        => $path,
      notify      => Exec["${name}-build"],
    }
  }

  $build_script = @("SCRIPT")
    #!/bin/bash
    set -ex -o pipefail
    export HOME=/root PATH=${path}
    cd ${dir}
    ${build_command} 2>&1 | tee build.log
    | SCRIPT

  file { "${dir}/build.sh":
    mode    => '0755',
    owner   => 'root',
    group   => 'root',
    content => $build_script,
  }
  ~>
  exec { "${name}-build":
    command     => "${dir}/build.sh",
    noop        => !$facts['build'],
    refreshonly => true,
    timeout     => 0,
  }
}
