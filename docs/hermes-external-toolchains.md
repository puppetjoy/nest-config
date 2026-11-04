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

The managed dependency installer also retains `UV_NO_MANAGED_PYTHON=1` and its
explicit system-backed interpreter. Runtime policy does not require that redundant
knob; `UV_PYTHON_PREFERENCE=only-system` supplies the discovery restriction.

## Normal apply ordering

Source acceptance is separate from deployment and retirement:

1. Review, test and merge Native's external-owner safeguards and this Nest policy.
   Preserve the accepted Broker pin and publish any new Native pin through the
   ordinary Nest source workflow; this policy change does not advance either pin.
2. The deployment owner uses the normal Bolt/Puppet deployment and inventory-backed
   apply. Existing catalog ordering synchronizes accepted Native source, writes
   the external stamp, installs dependencies, and publishes managed launchers and
   profile configuration before service activation. Do not run engineering with
   an incompatible Native policy while only part of that source tuple is active.
3. Verify a newly launched gateway/CLI, fresh engineering worker and terminal/test
   child: installation stamp, effective policy, actual executable and import
   origins must all match the accepted external installation. Environment strings
   alone do not prove executable provenance.
4. Only after consumer/provenance inventory and replacement acceptance may the
   deployment owner remove retired stores under their separate cleanup scope.
   This source change removes no stores and adds no migration or cleanup daemon.

For the coordinated retirement, ^2300 owns deployment, fresh-process acceptance
and cleanup. Its Nest prerequisite ^2301 releases on verified merged source and
this apply ordering, not on parent deployment or store deletion.

## Source validation

```sh
pdk validate
pdk test unit --tests=spec/classes/nest_app_hermes_spec.rb
```

The containing catalog suite covers the managed environment and launcher contract
alongside the existing external and PM-mode compatibility cases. Required exact-head
CI remains a release gate. Live-origin checks belong to deployment acceptance.
