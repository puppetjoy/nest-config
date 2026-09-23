# Restore a full Hermes-home generation from a native backup archive.
#
# By default this refuses to overwrite existing files; pass force=true for the
# native Hermes import --force behavior. All profile services are stopped while
# the shared root is replaced; --profile does not scope native imports.
plan nest::app::hermes::restore (
  String[1]           $archive,
  TargetSpec          $target   = 'owl',
  Boolean             $force    = false,
  String[1]           $user     = 'joy',
  Array[String[1], 1] $profiles = ['talon', 'star', 'beryl', 'quill'],
  # Deprecated compatibility input. Full-home imports are deliberately unscoped.
  Optional[String[1]] $profile  = undef,
) {
  $force_flag = $force ? {
    true    => '--force',
    default => '',
  }

  $profile_args = $profiles.shellquote
  $command = @("COMMAND"/L)
    set -euo pipefail
    test -f ${archive.shellquote}
    state_dir="$$(mktemp -d)"
    trap 'rm -rf "$${state_dir}"' EXIT HUP INT TERM
    for restore_profile in ${profile_args}; do
      for unit_type in gateway dashboard; do
        unit="hermes-$${unit_type}@$${restore_profile}.service"
        if systemctl --user -M ${user}@ is-active --quiet "$${unit}"; then
          : > "$${state_dir}/$${unit}"
        fi
        systemctl --user -M ${user}@ stop "$${unit}" || true
      done
    done
    runuser -u ${user.shellquote} -- /opt/hermes-agent/venv/bin/hermes import ${force_flag} ${archive.shellquote}
    for active_unit in "$${state_dir}"/*; do
      [ -e "$${active_unit}" ] || continue
      active_unit_name="$$(basename "$${active_unit}")"
      systemctl --user -M ${user}@ start "$${active_unit_name}" || true
    done
    | COMMAND

  return run_command($command, $target, 'Restore Hermes backup')
}
