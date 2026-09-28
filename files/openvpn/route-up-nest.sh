#!/bin/sh
# The VPN serves private domains whose negative replies can contain public-root
# DNSSEC denial records. Keep those records out of resolved's validated cache.
[ -n "${dev:-}" ] || exit 1
exec /usr/sbin/resolvectl dnssec "${dev}" no
