# Release watcher digest consolidation

## Before cron inventory (2026-06-08)

From `cronjob list` on Talon's profile:

| Job ID | Name | Schedule | Script | Mode |
|---|---|---:|---|---|
| `73f02b978224` | GitLab release watcher | `0 20 * * 3,4` | `gitlab_release_watch.py` | `no_agent` |
| `42bfd235d3ec` | Vaultwarden release watcher | `0 9 * * *` | `vaultwarden_release_watch.py` | `no_agent` |
| `140337254539` | Hermes Agent release watcher | `0 9 * * *` | `hermes_agent_release_watch.py` | `no_agent` |
| `a0debd826fef` | Kubernetes platform release watcher | `0 9 * * *` | `kubernetes_platform_release_watch.py` | `no_agent` |
| `00ec2f39562e` | WordPress release watcher | `0 9 * * *` | `wordpress_release_watch.py` | `no_agent` |
| `daa9c28afaf5` | Honcho stack release watcher | `0 9 * * *` | `honcho_stack_release_watch.py` | `no_agent` |

The old jobs were already token-cheap because they were `no_agent`, but they
were operationally noisy: five separate jobs all woke at 09:00, each maintained
its own state/signature and produced separate messages. GitLab also used a
separate release-cadence schedule. The consolidated script keeps the no-agent
model while emitting one classified daily digest.

## Consolidated coverage

`release_digest.py` covers the same watched stacks:

- Hermes Agent GitHub release vs installed Hermes package/managed venv
- GitLab release feeds vs live self-managed GitLab API version, plus chart context
- Vaultwarden server image, `guerzon/vaultwarden` chart, and Bitnami MariaDB chart
- WordPress Bitnami chart and upstream WordPress core vs chart image metadata
- Honcho server image, `honcho-ai`, CNPG PostgreSQL image, and Redis image
- Kubernetes platform pins: Rook/Ceph, Ceph image, Calico/Tigera, MetalLB,
  Contour, cert-manager, kube-prometheus-stack, NFS CSI, and ZFS LocalPV

The output is grouped by Joy-actionable classification:

- `ACTION NEEDED`: source/live pin drift that likely warrants an upgrade plan or
  maintenance window
- `WATCH ONLY`: drift worth knowing about but not automatically urgent
- `NO ACTION`: printed only with `--force`; scheduled cron stays silent when
  there is no drift and no watcher error

## Source-managed deployment

This branch adds a Puppet-managed script resource for Talon:

- Source: `files/app/hermes/release_digest.py`
- Destination when `release_digest_enabled: true`:
  `/home/joy/.hermes/profiles/talon/scripts/release_digest.py`
- Enablement: `data/host/owl.yaml` sets `release_digest_enabled: true` for the
  `talon` Hermes profile only.

## Proposed after cron inventory

After review/merge/deploy/apply, replace the six old release jobs with one
script-only cron job:

| Name | Schedule | Script | Mode | Delivery |
|---|---:|---|---|---|
| Daily Nest release digest | `0 9 * * *` | `release_digest.py` | `no_agent` | `origin` |

Suggested operator commands after Puppet has installed the script:

```bash
# Create the new daily digest job.
hermes -p talon cron create '0 9 * * *' \
  --name 'Daily Nest release digest' \
  --script release_digest.py \
  --no-agent \
  --toolsets terminal

# Pause/remove the superseded individual release watchers after the new job has
# produced a manual --force sample and one scheduled tick has succeeded.
hermes -p talon cron pause 73f02b978224
hermes -p talon cron pause 42bfd235d3ec
hermes -p talon cron pause 140337254539
hermes -p talon cron pause a0debd826fef
hermes -p talon cron pause 00ec2f39562e
hermes -p talon cron pause daa9c28afaf5
```

Use `cronjob list` immediately before changing live cron state: job IDs can
change across migrations. I did not mutate live cron state from this review
branch.

## Example digest output

`python3 files/app/hermes/release_digest.py --offline-sample`:

```text
Joy, here is the daily Nest release digest.

ACTION NEEDED
- Kubernetes platform: Rook/Ceph chart 1.18.2 -> 1.19.0
  Priority: high
  Context: Storage-platform maintenance: schedule a storage window; preflight test/prod Ceph health before rollout.
  Source: https://github.com/rook/rook/releases

WATCH ONLY
- Vaultwarden: guerzon/vaultwarden Helm chart 0.37.0 -> 0.38.0
  Priority: low
  Context: Chart-only maintenance: appVersion still matches the pinned server image; render before deciding whether to roll.
  Source: https://github.com/guerzon/vaultwarden/releases

Checked: 2026-06-08T20:00:00+00:00
Scope: Hermes Agent, GitLab, Vaultwarden, WordPress, Honcho, Kubernetes platform (Rook/Ceph, Calico, MetalLB, Contour, cert-manager, kube-prometheus-stack, NFS CSI, ZFS LocalPV).
```
