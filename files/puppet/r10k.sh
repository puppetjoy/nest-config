#!/bin/bash
#
# r10k container wrapper
#
# Run a custom r10k container image that supports all of the Nest platforms.
#
# See: https://gitlab.joyfullee.me/nest/tools/r10k
# See: https://gitlab.joyfullee.me/nest/config/-/blob/main/manifests/service/puppet.pp
#

exec podman run --rm --dns 172.22.4.3 \
    -v /srv/puppet/code:/etc/puppetlabs/code \
    -v /srv/puppet/r10k/config:/etc/puppetlabs/r10k:ro \
    -v /srv/puppet/r10k/cache:/var/cache/r10k \
    nest/tools/r10k \
    r10k "$@"

# vim: filetype=bash
