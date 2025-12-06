#!/bin/bash
#
# Bolt container wrapper
#
# Run a custom Bolt container image that supports all of the Nest platforms.
#
# See: https://gitlab.joyfullee.me/nest/tools/bolt
# See: https://gitlab.joyfullee.me/nest/config/-/blob/main/manifests/tool/bolt.pp
#

if [[ ! -f 'bolt-project.yaml' ]]; then
    echo "${PWD} is not a Bolt project" >&2
    exit 1
fi

name=$(ruby -ryaml -e 'puts YAML.load_file("bolt-project.yaml")["name"]')

PODMAN_SOCK='/run/podman/podman.sock'
if [[ -S "$PODMAN_SOCK" ]]; then
    podman_sock="-e CONTAINER_HOST -v ${PODMAN_SOCK}:${PODMAN_SOCK}:ro"
    export CONTAINER_HOST="unix://${PODMAN_SOCK}"
fi

exec podman run --rm -it -e TERM \
    --net=host --dns=127.0.0.53 \
    -w "/modules/${name}" \
    -v "${PWD}:/modules/${name}" \
    -v /etc/eyaml:/etc/eyaml:ro \
    -v /etc/puppetlabs/bolt:/etc/puppetlabs/bolt:ro \
    -v /etc/ssh/ssh_known_hosts:/etc/ssh/ssh_known_hosts:ro \
    -v /nest/home/kubeconfigs:/nest/home/kubeconfigs \
    -e KUBECONFIG \
    -e SSH_AUTH_SOCK -v "${SSH_AUTH_SOCK}:${SSH_AUTH_SOCK}:ro" \
    $podman_sock \
    nest/tools/bolt \
    bolt "$@"

# vim: filetype=bash
