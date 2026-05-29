#!/bin/sh
#
# run_puppet
#
# Initiate a Puppet run without background agent conflicts
#

set -u

restore_launchd_puppet=false

restore_launchd() {
  if [ "$restore_launchd_puppet" = true ]; then
    /bin/launchctl bootstrap system /Library/LaunchDaemons/org.voxpupuli.puppet.plist >/dev/null 2>&1 || true
  fi
}

trap restore_launchd EXIT

case "$(uname -s)" in
  Darwin)
    puppet_bin=/opt/puppetlabs/bin/puppet

    if [ ! -x "$puppet_bin" ]; then
      puppet_bin=$(command -v puppet 2>/dev/null || true)
    fi

    if [ -z "$puppet_bin" ]; then
      echo 'Unable to find Puppet executable' >&2
      exit 1
    fi

    if /bin/launchctl print system/puppet >/dev/null 2>&1; then
      /bin/launchctl bootout system /Library/LaunchDaemons/org.voxpupuli.puppet.plist
      restore_launchd_puppet=true
    fi
    ;;
  *)
    puppet_bin=$(command -v puppet 2>/dev/null || true)

    if [ -z "$puppet_bin" ] && [ -x /opt/puppetlabs/bin/puppet ]; then
      puppet_bin=/opt/puppetlabs/bin/puppet
    fi

    if [ -z "$puppet_bin" ]; then
      echo 'Unable to find Puppet executable' >&2
      exit 1
    fi

    if command -v systemctl >/dev/null 2>&1 && systemctl -q is-active puppet-run.timer; then
      systemctl stop puppet-run
    fi
    ;;
esac

# PUPPET_EXTRA_ARGS is already shell-quoted by the Bolt plan so it can carry
# optional arguments such as --environment, --noop, or --tags.
puppet_extra_args=${PUPPET_EXTRA_ARGS:-}

# shellcheck disable=SC2086
"$puppet_bin" agent --test $puppet_extra_args
status=$?

if [ "$status" -eq 2 ]; then
  exit 0
fi

exit "$status"
