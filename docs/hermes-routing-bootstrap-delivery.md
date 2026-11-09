# Routing-bootstrap managed source handback

## Source phase, not activation

This candidate prepares only the managed Broker routing prerequisite for the
main-chat integration. It does not remove conversational modes. No merge,
code deployment, Puppet apply, drain, pause, service restart, installed admission
or historical input replay is authorized by this document. The integration
owner must obtain a separate exact-source owner decision for live follow-through.
The earlier missing-Approve delivery is complete and its approval is not reused.

## Frozen source and ownership

Discovery verified Nest main `de30542af532e61a7ce9562ab2cee7d43fa3082f`
through fetch and authoritative `ls-remote`. Its managed Broker pin is
`3d21979a39dc4bd744e8c75146f9bb9f6d78ab75`.
The only runtime configuration change here is `data/host/owl.yaml`:

- Broker: `7e3002b1da165642477fd08993771e517263bfdd`, authoritative
  Broker main and merge of routing-bootstrap MR !248.
- Native core remains `df1b7bbaffb7de71db0d2a51b20bb68af616b205`, branch
  `nest`, with PM disabled. Every other Owl value is unchanged.
- The reviewed routing source `5c6ff0bf1f48c554a6c66fa4c023faec851cdc18`
  is an exact merge parent. Both the current managed pin and coordinated
  capability pin `2bec441617dd54098b177db30974f89ad2792327` are ancestors.
- The merge tree is `56e776b36a936458f34bf9b9ff371792079f7db8`. It is
  intentionally NOT identical to the routing source tree
  `cf1991eea1217218aa30962cafd2b10770f91ae8`: the merge preserves the
  separately accepted successor-source-continuation repair from MR !247.
  Against `2bec441617dd54098b177db30974f89ad2792327`, only the routing
  contract, `child_boundary.py` and its containing test file are added/changed.
  Never pin the older routing branch tip and lose the accepted continuation work.

Shared hotspot: `data/host/owl.yaml`. Existing draft Nest MR !719 at
`e48e42b866aae872fd2f853f571cf2b7a8d0b556` prepares the older coordinated
Broker pin. Its owner remains responsible for that retained source and safety
prerequisites. This distinct successor does not close, overwrite or deploy it.
Before merge, the integration owner must reconcile both source phases with one
rollout owner and fresh remote/pin reads. Do not merge a stale pin over newer
accepted work. Wizard and Telegram reliability owners retain their Native work;
this candidate neither selects their unmerged core nor depends on their entire
product completion.

## Validation and consumer boundary

Run the existing managed Broker contract with the canonical focused PDK command:

```sh
pdk validate
pdk test unit --tests=spec/files/hermes_broker_runtime_spec.rb
python3 spec/files/hermes_build_state_test.py
python3 spec/files/hermes_frontend_build_test.py
python3 spec/files/hermes_source_sync_test.py
```

Use the immutable PDK image declared in `.gitlab-ci.yml` when invoking PDK in
its container. Keep PDK invocations serial. The Broker contract executes the
rendered plugin entry point and checks independent immutable pins, editable
canonical import origins and restricted Broker runtime tagging. Source-sync
fixtures exercise drift refusal, interrupted convergence and rollback. Optional
real-core coverage must explicitly identify its read-only object source; a
skipped optional case is not a passed real-source acceptance check.

Require this candidate's exact-head CI, the actual merged Broker pipeline at
`7e3002b1da165642477fd08993771e517263bfdd`, and all required jobs before
any rollout decision. Routing-source pipeline 13172 alone does not test the
merged composition. Record exact pipeline IDs, heads, required job states and
independent semantic source review in the accompanying handback receipts.

## Inventory-backed future workflow

These are future commands, not commands executed by this source preparation.
Run from the final accepted Nest project root with its own declared modules,
`bolt-project.yaml`, inventory and modulepath; use `bolt module install` if
needed. Preserve exact working directory and stdout/stderr for every failure.
Do not use direct SSH or ad-hoc remote Puppet as a fallback.

```sh
bolt inventory show owl --detail --format json
bolt command run 'id -un && hostname -f' --targets owl --stream
```

Expected transport is `joy@owl` with Bolt-managed root escalation. Use the
profile's existing managed identity, not Joy's personal key. Independently read
installed core/Broker revisions, import origins and environment ownership through
this transport before choosing an activation. Inventory proof does not authorize
mutation. Require current source ancestry, exact configuration MR/head, successful
merged-main CI after an authorized merge, and explicit approval covering the
whole final source tuple and consumer-refresh impact.

The repository code-publish and host-convergence plans are:

```sh
bolt plan run nest::puppet::deploy backend=prod environment=main --stream
bolt plan run nest::puppet::run targets=owl noop=true --stream
bolt plan run nest::puppet::run targets=owl --stream
```

The deploy plan updates production OpenVox r10k code and expires the compiler
cache; it is a live mutation, not harmless preparation. Read the noop catalog
before apply and stop for unrelated drift or source changes. Ordinary full
convergence can refresh gateway consumers and affect other managed resources;
a Broker-only Hiera diff is NOT proof of a Broker-only operational blast radius.
The existing runtime tag only selects checkout/install; it is not a complete
consumer refresh or safe-maintenance protocol. Do not silently substitute a tag
or an unreviewed restart. Any alternative must be explicitly scoped and approved.

## Maintenance bootstrap and custody gate

An independent apply unit survives a gateway disconnect but does not preserve
active workers, unsettled Telegram updates, media batch tails or uncertain sends.
The retained coordinated rollout currently lacks a qualified installed-compatible
maintenance bootstrap and complete transport/raw-media/epoch-bound custody. This
is an activation obstruction, not a source-preparation obstruction. No fence from
a future uninstalled core may be assumed to protect the running old gateway.

Before any gateway-affecting step the activation owner must verify a supported
boundary on the ACTUAL installed core: durable queue-only intake admission,
transport acknowledgment and media ownership settlement, worker scheduling and
claim fencing, active-worker continuation custody, pending off-loop mutations,
outbound attempt/settlement identities and a bounded abort returning the same
preserved FIFO. Preserve every profile's delivery ledger and retained private
media. Failure to establish any boundary means STOP before apply; obtain a
separately qualified source prerequisite rather than inventing a second cutover
controller or forcing a restart. This source handback cannot certify that gate.

After those gates and exact owner approval, the activation owner records a
credential-free independent user-manager unit design with explicit working
directory, the exact Bolt argv, existing KUBECONFIG path/environment requirements,
source tuple, approval identity and private output directory outside any worker
or cleanup-prone checkout. Resolve authenticated CI gates before launching the
unit; it must not need borrowed worker GitLab credentials.

Persist the unit name, attempt identity and exclusive create-only launch marker
before Bolt starts. Retain complete private stdout/stderr, start/end observations,
unit invocation identity, Result/ExecMainCode/ExecMainStatus and final exit receipt
outside the gateway process tree. A separately readable task attachment should
carry only sanitized source, unit and outcome metadata, never credentials, chat
payloads or raw media. Demonstrate that the executor is outside the gateway's
kill scope and that the receipt is independently readable before launch. These
are required receipt fields and custody checks, not a new deployment framework.
No unit, attempt marker or apply receipt has been created by this preparation.

## Reconnect, acceptance and rollback

On disconnect, observe the SAME retained unit invocation, its complete log and
exit receipt; independently inspect installed checkout/import identities and
Puppet result. A lost terminal response, absent success message, timeout or EOF
is uncertain, not permission to rerun. Do not resend code deployment, apply,
notification, callback, approval or external operation. If a unit has disappeared
without conclusive evidence, retain uncertainty and diagnose from immutable
receipts; never allocate a fresh attempt merely to get a green exit.

After a proven successful authorized apply, use fresh ordinary and isolated
managed Python processes to check Broker HEAD and canonical origin
`/opt/hermes-agent/agent-request-broker/src`, preserved Native HEAD/origin
`/opt/hermes-agent/src`, system-owned interpreter, external-owner install stamp
and no retired PM import roots. Verify genuinely refreshed consumer PID/source
identity rather than an old long-lived adapter import. Then let the original
integration owner perform supported query-only routing preflight and public
allocation under its own fresh owner/run proof. Never borrow its claim. Test
stale/foreign/missing evidence refusals and retained history. Installed routing
admission is not modal-removal deployment or original incident recovery.

Before apply retain the actual prior installed Broker/core tuple, code and
runtime receipts plus usable backups of private state under existing policy.
Rollback is source-managed and separately authorized: restore only the Broker
pin to the verified prior installed revision through reviewed configuration,
CI, code-publish and ordinary Bolt convergence with the SAME safety gates. Do
not assume main's initial pin is still the installed rollback target after other
owners advance source. No core rollback, database restore, queue deletion,
authorization reuse or delivery replay is implied. Broker downgrade may refuse
newer state; inspect compatibility first and retain history rather than forcing
it. If maintenance cannot protect rollback, stop without restarting and return
the exact obstruction to the single activation owner.

## Finite handback

The source phase ends with an unmerged draft MR/head, exact changed files,
independent semantic review and managed/consumer/CI receipts, this activation
scope and the explicit custody obstruction above. Parent owns the fresh rollout
decision, installed admission and later modal-removal integration. Preparation
may complete without waiting for parent completion; no deployment or recovery
claim follows from source readiness.
