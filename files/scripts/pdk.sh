#!/bin/bash
#
# PDK container wrapper
#
# Run a custom Puppet Development Kit container image that
# supports all of the Nest platforms.

# See: https://gitlab.joyfullee.me/nest/tools/pdk
# See: https://gitlab.joyfullee.me/nest/conifg/-/blob/main/manifests/tool/pdk.pp
#

exec podman run --rm -it -e TERM \
    -v "${PWD}:/module" \
    -v pdk-empty:/module/.resource_types:ro \
    -v /etc/eyaml:/etc/eyaml:ro \
    nest/tools/pdk \
    pdk "$@"

# vim: filetype=bash
