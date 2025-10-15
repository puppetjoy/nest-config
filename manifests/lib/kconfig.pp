define nest::lib::kconfig (
  Stdlib::Absolutepath $config,
  Nest::Kconfig        $value,
  String               $setting = $name,
) {
  $line_ensure = $value ? {
    undef   => 'absent',
    default => 'present',
  }

  $line = $value ? {
    Numeric   => "${setting}=${value}",
    'n'       => "# ${setting} is not set",
    /^(y|m)$/ => "${setting}=${value}",
    'Y'       => "${setting}=y",
    default   => "${setting}=\"${value}\"",
  }

  file_line { "kconfig-${title}-${value}":
    ensure            => $line_ensure,
    path              => $config,
    line              => $line,
    match             => "(^| )${setting}[= ]",
    match_for_absence => true,
  }
}
