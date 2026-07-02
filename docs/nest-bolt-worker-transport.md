# Nest Bolt worker SSH transport

Agent Request workers should use the inventory-backed Bolt path for Nest host follow-through:

```sh
bolt inventory show owl --detail --format json
bolt command run 'id -un && hostname -f' --targets owl --stream
bolt plan run nest::puppet::run targets=owl noop=true --stream
```

The intended transport for Gentoo Nest hosts is:

- SSH to the unprivileged `nest::user` account (`joy`), not direct `root` SSH.
- Let OpenSSH/default identity handling choose either the mounted ssh-agent socket or the default key present in the caller environment.
- Let Bolt plans/tasks escalate when needed with `_run_as => 'root'`.

This distinction matters for Hermes/Agent Request workers. The Bolt wrapper runs the Nest `nest/tools/bolt` container as root, so a project inventory `private-key: '~/.ssh/id_ed25519'` expands inside the container as `/root/.ssh/id_ed25519`. That works only for callers that mount a root key into the Bolt container. Talon Agent Request workers usually have the host ssh-agent socket and profile Git key material available instead, so forcing `/root/.ssh/id_ed25519` makes Bolt attempt `root@owl.nest` or a missing/unusable root key and report `Authentication failed`.

The source-managed fix is deliberately split:

1. `inventory.yaml` sets Gentoo host SSH user to `joy` and stops forcing a global private-key path. Kube/pod targets can still rely on their own root-key mount/default identity behavior, while Gentoo host Puppet runs connect as `joy` and escalate through Bolt.
2. `templates/scripts/bolt.sh.epp` exports `/run/user/$(id -u)/ssh-agent.socket` when `SSH_AUTH_SOCK` is absent but that standard user agent socket exists, then mounts it into the Bolt container.

If the smoke command fails, preserve the exact Bolt command, working directory, inventory file, target detail, and stderr/stdout. Do not switch the final deployment strategy to direct SSH or ad-hoc Puppet; diagnose why the inventory-backed Bolt path cannot authenticate or escalate.
