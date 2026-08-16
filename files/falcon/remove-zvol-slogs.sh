#!/bin/sh
set -eu

DATA_OLD=/dev/zvol/falcon/slog/data-part1
NEST_OLD=/dev/zvol/falcon/slog/nest-part1

status_has_device() {
  pool="$1"
  device="$2"
  resolved=$(/usr/bin/readlink -f "$device" 2>/dev/null || true)

  /sbin/zpool status -P "$pool" | /bin/grep -Fq -- "$device" ||
    { test -n "$resolved" && /sbin/zpool status -LP "$pool" | /bin/grep -Fq -- "$resolved"; }
}

remove_log() {
  pool="$1"
  old="$2"

  if status_has_device "$pool" "$old"; then
    /sbin/zpool remove "$pool" "$old"
  fi

  if status_has_device "$pool" "$old"; then
    printf 'Unsafe ZVOL-backed SLOG remains attached to %s: %s\n' "$pool" "$old" >&2
    return 1
  fi
}

# The data pool remains a mirrored pair of SSDs. The nest pool falls back to its
# pool-local ZIL. Both retain standard synchronous-write semantics without the
# cross-pool recursion that deadlocked all three pools.
remove_log data "$DATA_OLD"
remove_log nest "$NEST_OLD"
