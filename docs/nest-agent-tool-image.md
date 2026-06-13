# Nest agent tool image

`nest/tools/agent:latest` is the generic Hermes agent terminal-runtime image for container-backed agent sessions. It is built from `nest/stage1/server` with the existing `nest::build::tool` plumbing and the `nest::tool::agent` Puppet class.

## Build and publish

The v1 image intentionally publishes only one tag:

- `registry.gitlab.joyfullee.me/nest/tools/agent:latest`

Build it for the current Nest x86_64 workstation/server target with:

```sh
./bin/build agent zen5 deploy=true registry=registry.gitlab.joyfullee.me
```

GitLab CI has a `Build agent tool zen5` job for default-branch pipelines when `BUILD=agent` is set. The job calls the same Bolt plan and publishes `latest` to the GitLab registry only; there is no Eyrie registry mirror for this initial version.

## Runtime contents

The v1 image is intentionally a thin wrapper around `nest/stage1/server`. This creates a stable `nest/tools/agent` image name and `nest::tool::agent` extension point for Beryl and future Hermes profiles without baking in profile-specific data or prematurely choosing a large package set.

It does not bake in profile data, secrets, kubeconfigs, tokens, SSH keys, browser profiles, or other profile-specific Hermes state.

## Smoke test

The build plan starts the built container and verifies basic terminal command execution through the image:

```sh
/bin/zsh -lc "print nest-agent-terminal-smoke"
```

This is intentionally a terminal-runtime smoke test. Hermes browser tools are host-side Hermes tools, so Beryl does not need this container image in order to receive `browser_*` capabilities.

## Beryl runtime wiring

Beryl's Puppet-managed Hermes terminal backend now points at:

```yaml
docker_image: registry.gitlab.joyfullee.me/nest/tools/agent:latest
```

Beryl already uses a persistent Hermes Docker/Podman terminal container. No separate persistent browser profile or cache directory is required for v1 because browser sessions are not provided by this image.
