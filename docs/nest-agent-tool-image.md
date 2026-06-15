# Nest agent tool image

`nest/tools/agent:latest` is the generic Hermes agent terminal-runtime image for container-backed agent sessions. It is built from `nest/stage1/server` with the existing `nest::build::tool` plumbing and the `nest::tool::agent` Puppet class.

## Build and publish

The v1 image intentionally publishes only one tag:

- `registry.gitlab.joyfullee.me/nest/tools/agent:latest`

Build it for the current Nest x86_64 workstation/server target with:

```sh
./bin/build agent zen5 deploy=true registry=registry.gitlab.joyfullee.me
```

The public project at <https://gitlab.joyfullee.me/nest/tools/agent> owns the default-branch GitLab pipeline for this image, matching the other `nest/tools/*` projects. Its `gitlab-ci.yml` runs the source-managed `nest::build::agent` plan from this `nest/config` repository through the published config builder image, then pushes `latest` to the GitLab registry only. There is no Eyrie registry mirror for this initial version.

The build recipe remains in `nest/config` because it is Puppet/Bolt source for Nest's shared tool-image framework; the `nest/tools/agent` project is the discoverable source/pipeline entry point for the registry namespace.

## Runtime contents

The image is a shared Hermes terminal-runtime wrapper around `nest/stage1/server`. It creates a stable `nest/tools/agent` image name and `nest::tool::agent` extension point for Beryl and future Hermes profiles.

It does not bake in profile data, secrets, kubeconfigs, tokens, SSH keys, browser profiles, or other profile-specific Hermes state.

It does include the official GitLab CLI package, `dev-util/gitlab-cli`, which installs `glab`, via the shared `nest::tool::gitlab_cli` class. The host-side Hermes install also contains that class so Talon, Star, and other non-container Hermes profiles have `glab` in `/usr/bin` without relying on the agent image. Agent-specific GitLab tokens still come from each Hermes profile's Puppet/private eyaml secret path and are injected at runtime, not baked into the image.

On Gentoo/Nest hosts the package is currently source-managed as `dev-util/gitlab-cli` with `unstable => true`, matching the overlay/package-manager constraint for the current upstream GitLab CLI ebuild.

## Smoke test

The build plan starts the built container and verifies basic terminal command execution through the image:

```sh
/bin/zsh -lc "print nest-agent-terminal-smoke"
glab --version
```

After rebuilding and deploying the image, verify Beryl's actual persistent terminal runtime with non-secret checks like:

```sh
command -v glab
glab auth status --hostname gitlab.joyfullee.me
curl --fail --silent --show-error --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" "${GITLAB_URL}/api/v4/user" | jq '{username, id}'
```

The `/user` response must identify Beryl, and token values must not be printed in logs, comments, commits, or handoffs.

This is intentionally a terminal-runtime smoke test. Hermes browser tools are host-side Hermes tools, so Beryl does not need this container image in order to receive `browser_*` capabilities.

## Beryl runtime wiring

Beryl's Puppet-managed Hermes terminal backend now points at:

```yaml
docker_image: registry.gitlab.joyfullee.me/nest/tools/agent:latest
```

Beryl already uses a persistent Hermes Docker/Podman terminal container. No separate persistent browser profile or cache directory is required for v1 because browser sessions are not provided by this image.
