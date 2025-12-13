#!/bin/zsh
#
# GitLab Runner container wrapper
# See: https://gitlab.joyfullee.me/nest/config/-/blob/main/manifests/service/gitlab_runner.pp
#

exec podman run --rm -it -e TERM \
    --dns=172.22.4.3 \
    --entrypoint=/usr/bin/gitlab-runner \
    -v /srv/gitlab-runner:/etc/gitlab-runner \
    alpinelinux/gitlab-runner $@
