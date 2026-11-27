# Externally owned Hermes toolchains

Nest/Gentoo owns host executables, including Python, uv, Node/npm, ffmpeg and
ripgrep. With `nest::app::hermes::pm_enabled: false`, Hermes must neither acquire
private executable bundles nor select retained private bundles. Native enforces
that boundary using the existing external-owner installation stamp.

## Managed process policy

The managed CLI and Python wrappers, profile commands and profile `systemd.env`
export these non-secret settings (paths follow `install_dir`):

```text
HERMES_INSTALL_ROOT=/opt/hermes-agent/src
UV_PYTHON_DOWNLOADS=never
UV_PYTHON_PREFERENCE=only-system
```

`HERMES_INSTALL_ROOT` locates Native's installation stamp; it is not another
package manager or a new ownership switch. The uv settings forbid interpreter
downloads and exclude uv-managed interpreter discovery. `never` alone does not
exclude reuse of already downloaded interpreters. These settings do not disable
ordinary dependency downloads, isolated virtualenvs based on Gentoo Python, or
unrelated projects. Engineering should select `/usr/bin/python3.14` explicitly
when constructing a Hermes test environment and verify its base interpreter.
No global uv configuration or forced offline setting is installed.

Gateways and dashboards read the existing profile `systemd.env`. Managed terminal
configuration adds the policy names to `terminal.env_passthrough` while preserving
existing backend settings and passthrough entries. Fresh engineering workers and
their terminal children must inherit this installation policy. Native must treat
these values as process-global, not profile credentials, including multiplexed
worker launches. The canonical test runner must preserve them in its child
environments. Policy is not stored in credential `.env` files.

The managed dependency installer uses the same policy and an explicit
system-backed interpreter. Do not combine `UV_PYTHON_PREFERENCE=only-system`
with `UV_NO_MANAGED_PYTHON` or `--no-managed-python`: uv rejects that redundant
combination before exporting or checking dependencies. The single preference
already excludes retained managed interpreters; downloads remain forbidden.

## Normal apply ordering

Source acceptance is separate from deployment and retirement:

1. Use the owning repository’s ordinary MR for app changes. Owl follows Hermes
   `nest` and Broker `origin/main`; neither requires a Nest Config pin update for
   routine releases. Follow [Routine Owl delivery](hermes-managed-source-transition.md#routine-owl-delivery)
   for authorized activation and rollback. A merge alone does not authorize an apply.
2. For an authorized change to the external toolchain policy, the existing
   Bolt/Puppet path writes the external stamp, installs dependencies, and
   publishes managed launchers and profile configuration before service
   activation. Do not use a partly updated runtime for engineering work.
3. Verify the installation stamp, effective policy, executable and import
   origins from the affected consumer. A fresh CLI or managed Python process
   verifies the installed runtime; it does not prove a resident gateway reloaded
   or authorize restarting one. For policy changes that affect worker and test
   children, verify their executable provenance as well as their environment.
4. Remove retired stores only after verifying their consumers and replacements,
   and only within the separately authorized cleanup scope.

The coordinated ^2300/^2301 retirement was a one-time migration. Its
[original handoff](https://gitlab.joyfullee.me/nest/config/-/blob/10656ad478250164e000b213dd9ee436409b0547/docs/hermes-external-toolchains.md#normal-apply-ordering)
remains available for history; it is not a prerequisite for ordinary releases.

## Source validation

```sh
pdk validate
pdk test unit --tests=spec/classes/nest_app_hermes_spec.rb
```

The containing catalog suite covers the managed environment and launcher contract
alongside the existing external and PM-mode compatibility cases. Required exact-head
CI remains a release gate. Live-origin checks belong to deployment acceptance.
