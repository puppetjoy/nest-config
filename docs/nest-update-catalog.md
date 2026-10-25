# Normal main catalog and unchanged repeat

`nest::host::update_catalog target=HOST` executes the existing managed Puppet
wrapper on exactly one inventory-backed Linux host, using ordinary Bolt root
escalation. This is a mutating operation, not an observation, noop, tagged
package installation, offline build or replacement deployment mechanism.
Do not invoke it merely to verify that its source has been installed.

The plan requests the complete `main` environment with noop, cached-catalog
reuse and cache-on-failure disabled, and with both tag filters empty. It
supplies no build or kernel-only fact override. Existing native agent/service
coordination, platform handling and per-run lock remain in the managed wrapper.
It does not weaken transport, change credentials, retry a failed catalog,
reset/reboot, clear failed units or record transaction acceptance.

The first apply must return the actual detailed native exit 0 or 2 before a
second apply is attempted. Only repeat exit 0 is converged. A repeat exit 2
still means changes and fails convergence; exits 1, 4, 6 and unexpected codes
remain failures, never success. Missing exits, including a caught transport
error, are null and cannot pass. There is no third apply or loop. A plan can
return successfully with `result: fail`; inspect the returned outcome, not just
Bolt's exit. A transport fault with unknown completion must be inspected before
an operator reruns this mutating plan.

The result is schema 1, kind `nest_update_catalog`, containing `main_exit`,
`repeat_exit`, `repeat_attempted`, `converged`, `requested_environment: main`,
`served_source_verified: false` and `acceptance_recorded: false`. Raw catalog
logs are not copied into this returned document. Normal Bolt logs may contain
private catalog output; do not attach those without reviewing them.

## Coverage boundaries

This plan establishes native apply/repeat exits for requests to main. It does
not prove the exact source of the catalog actually served, stable boot identity,
expected transaction/release, or that two catalogs have the same source. An
unchanged repeat is not an assertion that unrelated writers could not act
between runs: the existing lock is held per apply, not across the pair. It does
not bound the duration of a full Puppet run or add timeout/kill semantics that
might leave a partially applied catalog.

Later lifecycle integration must bind real served report/source identities and
both catalog results to the expected host/boot, release and real preparation,
retain sanitized artifacts, and collect the remaining service/hardware gates
before acceptance. A configured main request is not exact-main source proof.
This interface is intentionally not composed into the read-only
`nest::host::update_health` plan; doing so would silently turn observation into
host mutation. No live full catalog was applied to test this interface.

## Read-only native report binding

`nest::update_catalog_report` is a separate read-only task. Run it with the
ordinary inventory-backed Bolt transport and root escalation, using a private
JSON parameter file: `bolt task run nest::update_catalog_report --targets HOST
--run-as root --params @PARAMS.json`. The file has one `expectations` object:

- `hostname`: exact Linux hostname, and `certname`: exact Puppet certname.
  These are independent identities; neither is inferred from the target alias.
- `boot_id`: expected current Linux boot UUID.
- `configuration_version`: exact full forty-character lowercase Git SHA.
- `transaction_uuid`: actual native Puppet transaction UUID for this invocation,
  not the Nest update transaction ID or a newly invented UUID.
- `status`: `changed` or `unchanged`, consistent with the retained native exit.
- `not_before` and `not_after`: integer epoch bounds on the native report's start
  time, spanning at most one day. Choose them from actual invocation evidence,
  not merely from the age of whatever report happens to exist.

The task reads the agent-configured `lastrunreport`, using the installed agent's
settings and certname. It requires a root-owned regular non-group/world-writable
file, refuses symlinks, reads at most 32 MiB and has a thirty-second collection
deadline. It parses the native YAML syntax tree without deserializing Ruby
objects, following aliases or returning resource/log bodies. Missing fields,
wrong source/host/boot/transaction/time/status, incomplete transactions, noop,
cached catalogs, duplicate keys and changed report bytes or boot IDs all refuse.
JSON-formatted reports are not supported and fail closed rather than guessed.

Successful output has schema 1, kind `nest_update_catalog_report`, a sanitized
`report` object with selected native scalars and `report_sha256`, the observed
hostname and boot ID, and `acceptance_recorded: false`. Task failure returns a
generic error without leaking the report. Native `catalog_uuid` is also retained.
This observes one report; it never applies a catalog, repeats an apply, clears a
failure, changes a transaction, or records acceptance.

The managed environment now emits the complete Git configuration version, not
an abbreviated commit. Older abbreviated reports deliberately fail exact-source
binding. This does not require replaying an apply just to test installation.
The version describes the server's configured Git revision, not independently
attested module bytes or a clean server checkout. Report digest readback does
not authenticate catalog content or independently attest served modules.
Lifecycle acceptance uses the ordinary
Git configuration version and native report results; module-byte attestation is
not required for this personal distro.

The legacy apply/repeat path without expectations does not capture a report
under the agent lock. A separate task read cannot prove that a concurrent agent did not
replace a report before the first observation. Callers must supply an actually
retained invocation UUID/window, not adopt the current report as proof of their
own run. This task therefore does not change `served_source_verified: false` in
the apply/repeat plan, satisfy release acceptance, or substitute for the remaining
boot/release binding, atomic invocation capture and durable report integration.

## Invocation-bound apply and repeat

For a reviewed real catalog operation, pass an `expectations` hash to
`nest::host::update_catalog`, or invoke `nest::update_catalog_apply` directly
with ordinary inventory-backed Bolt root escalation. This is MUTATING and
Linux-only; it is not an installation check and does not support noop. The four
required expectations are exact `hostname`, `certname`, current `boot_id`, and
full `configuration_version` SHA. The plan still requires exactly one host.
Without expectations the previous unbound interface is unchanged.

The task invokes the same managed shell wrapper, not an alternate agent or
deployment mechanism. Each apply gets a newly created mode-0700 directory in
the agent's root-owned, non-group/world-writable `statedir`, with separate native
`--lastrunreport` and `--lastrunfile` paths passed as argv, never reparsed shell
text. Native report storage writes directly to that unique location before the
agent exits. A concurrent later run cannot overwrite it by publishing its own
ordinary last report. The task observes the native transaction UUID from this
invocation-private file rather than accepting a UUID guessed by the caller or
adopting the shared last report. It requires different UUIDs across the pair.

For each successful native exit, the existing safe YAML scalar parser checks
exact host, full source, main environment, start window, status consistent with
exit 0/2, completion, non-noop and no cache reuse. Report bytes are reread before
proceeding. Boot identity is checked before the first apply, between applies and
after the repeat. A failed exit, missing or invalid report, changed boot or
wrong source stops without another apply. There is at most one repeat, and
only repeat exit 0 with a bound report is converged. Failed report binding
retains its known native exit; unknown/signal exits remain null.

The result has kind `nest_update_catalog_bound`, sanitized `main` and optional
`repeat` receipts with `native_exit`, `report_bound` and selected report scalars,
plus `repeat_attempted` and `converged`. Inspect `result`, not just Bolt's exit:
known failed convergence returns a structured failure. Transport or invocation
ambiguity must be inspected before manually rerunning; neither plan nor task
automatically retries it. The task does not timeout/kill a running native apply.
Private local report/summary/log files are removed after collection, not copied
to public output. Server-side native reporting remains configured normally;
these invocations intentionally do not overwrite the shared local last report
or summary. After an interrupted task, private remnants can remain in statedir;
never blindly replay an apply based on those remnants or a transport timeout.

The wrapper still holds its existing lock per apply, not across the pair. A
failed blocking flock now refuses instead of proceeding unlocked. Missing
`flock` retains the legacy wrapper behavior; Puppet's native agent coordination
is not bypassed. Build/skip-module fact overrides and extra argument overrides
are removed for the bound task. Native report isolation proves invocation
provenance without requiring a lock to remain held during later readback.

This is still NOT release acceptance: the task does not verify the prepared
release/root/BE, historical failure dispositions or service/hardware/physical UX.
Independent served-module attestation is not a release requirement. Consequently
`served_source_verified` and `acceptance_recorded` remain false. Lifecycle
integration must retain these receipts durably with real release/boot evidence
before accept/finalize. No real host catalog was applied to validate this code.

## Durable supervisor retention for bound invocations

For a reviewed real catalog operation, `nest::host::update_catalog` also accepts
optional `retention`, with exactly `transaction`, `release` and `output_dir`.
It requires the four invocation `expectations`; it cannot be combined with the
unbound compatibility path. The transaction is a bounded native Nest ID and
release is `sha256:` plus the full release-manifest digest. These are requested
context, NOT independently verified preparation or release acceptance.

Precreate `output_dir` on persistent supervisor storage. With the Nest Bolt
container wrapper use a path under `/modules/nest/rollout-evidence/ROUND`, backed
by the caller's project directory. A container-local temporary directory is not
durable outside that container. The plan first invokes
`nest::retain_update_catalog action=check` on `localhost` to validate the complete
context and canonical existing directory, before any host apply. This read-only
check creates no directory or lock and does not guarantee future writeability,
free space or exclusive ownership. It does not itself execute a catalog.

After the bound task returns, the plan passes its exact JSON result to
`nest::retain_update_catalog action=retain` on that same supervisor. The task
validates host, boot, full source, certname, native UUIDs and detailed exits,
completion/non-noop/non-cache flags and outcome consistency. It rejects unknown
fields rather than copying arbitrary logs or private resource data. Valid failed
or unknown native exits, changed repeats and explicit identity-binding failures
are retained as failures, not silently discarded or promoted to success.

The retained schema-1 `nest_update_retained_catalog` contains the sanitized
invocation result, exact expectations, requested transaction/release context and
transport digest. `release_binding_verified`, `served_source_verified` and
`acceptance_recorded` are all false. This validates the transported selected
native scalars; it cannot rehash already removed private raw YAML, authenticate
catalog content or prove the served module bytes. The raw-report digest remains
the actual producer observation, not a newly verified raw-report digest here.

Publication reuses the existing report helper's fsync, no-clobber hard link and
exact-byte/JSON readback. The public allowlisted document is mode 0644 with a
content-addressed `catalog-TRANSACTION-DIGEST.json` name. Equal concurrent copies
are idempotent; changed observations retain distinct files; conflicting bytes or
symlinks at the exact target refuse without replacement. There is no pruning.
The plan adds `retained_report` containing the exact path, digest, byte count,
readback flag and outcome. A successful return with `result: fail` is still a
failed catalog outcome. Destination or publication failure fails the plan;
it never repeats a host apply to recover a missing artifact. After a transport
or retention error, inspect the real invocation before any manual replay.

Before task completion, reopen the corresponding caller-side path, compare the
returned digest, context and result, and retain the file through the existing
task artifact API. Supervisor readback is not notification-host delivery. This
integration does not call `nest reset accept`, finalize a transaction, add a
background supervisor or turn the read-only health plan into a mutating plan.
No real host catalog was applied to test retention. Rollback omits `retention`,
preserving existing evidence and all ambiguity; it cannot undo prior applies.

## Complete runtime release metadata binding

For lifecycle callers, pass `release_manifest` to `nest::host::update_catalog`
alongside both exact `expectations` and `retention`. The value is the complete
`nest_release_manifest`, not a validation receipt or one selected output.
Without both prerequisites the plan refuses before any task or host apply.
Existing callers omitting this parameter retain their previous result shape.

The supervisor retainer validates the entire expected matrix, input sources,
producer/executor identities and output structure using the existing release
validator. Its canonical digest must equal `retention.release`, the requested
configuration version must equal the manifest's exact `nest/config` source,
and the expected hostname must be a unique Stage 3 output member. Other missing
or changed members invalidate the runtime digest too. Hostname is not silently
derived from an inventory alias, and certname remains a separate identity.

These checks run before the first mutating catalog invocation and again before
retention. Invalid metadata stops without applying, publishing, retrying or
repairing. A later publication failure never causes another host apply. The
existing invocation validator still binds both native reports to the same exact
configuration version, certname and boot, with detailed first/repeat exits.
Valid failed outcomes remain failures even with matching release metadata.

The retained document adds only `release_metadata`: runtime manifest digest,
config SHA, hostname, Stage 3 member and versioned root reference. It does not
copy the complete manifest or arbitrary private data into the public report.
The retention check and final receipt add `release_metadata_bound: true` and
`manifest_digest`. Raw catalog reports retain their existing bounded size;
the complete task parameter envelope is bounded to 2 MiB. Publication still
uses the same atomic, no-clobber, reopened supervisor files.

This is metadata reconciliation, NOT independently verified served module bytes,
preparation/GUID/boot continuity, actual publication resources, a retention lease
or transaction acceptance. `resource_verification` is `not_performed`, while
`release_binding_verified`, `served_source_verified` and `acceptance_recorded`
remain false. It does not call native accept/finalize or authorize a catalog,
reset or reboot. Full lifecycle integration must verify those remaining gates;
matching metadata must not be promoted into operational acceptance.

Rollback stops this interface or omits `release_manifest` for explicitly legacy
callers while preserving all receipts. Do not use the compatibility interface
to bypass a refused release-aware lifecycle. Reopen and retain exact caller-side
files before completion as described above. No real host apply is needed to
exercise manifest validation, staging or isolated composition tests.

## Optional native catalog code identity

The same `expectations` object also accepts optional `code_id`, spelled exactly
`sha256:` followed by 64 lowercase hexadecimal digits. This is separate from
the Git `configuration_version`. The value must come from an independently
reviewed compiler/release identity; never adopt the current report's value as
its own expectation or substitute an executor digest for the compiler's identity.
OpenVox carries the native catalog code ID into `Puppet::Transaction::Report`;
the collector reads that scalar without instantiating YAML objects.

With this expectation, the read-only report task requires an exact native
`code_id`. The bound apply task checks it on each invocation-private report.
A missing, null or different first ID retains the native exit and stops before
the repeat. A changed or missing repeat ID cannot converge and never causes a
third apply. Invalid expectation syntax refuses before any apply. The supervisor
preflight and retainer validate the same expectation and both selected report
scalars; the existing atomic publication/readback preserves the IDs and the
expectation in the retained document. Stripping a required ID during transport
refuses instead of silently falling back to the older source-only contract.

Callers omitting `code_id` retain the original output shape and checks, including
deliberately omitting any unsolicited native code ID from the selected output.
This compatibility path must not bypass a refused release-aware operation.
Existing native reports without a code ID cannot satisfy the opt-in contract;
do not replay real catalogs merely to create evidence for this feature.

This adds native identity reconciliation, not a compiler attestation. It does not
configure a server code-ID command, freeze a mutable server module tree, prove
compiler-cache identity or establish what a server-generated digest represents.
`served_source_verified`, `release_binding_verified` and `acceptance_recorded`
remain false. Independent served-module attestation and native code IDs are not
required for the ordinary r10k/OpenVox update path. Full lifecycle acceptance
still needs real release/boot, health and native catalog results. Tests use actual
OpenVox report serialization and inert apply runners, not production catalogs.
Rollback omits the optional field only for explicitly legacy callers, preserving
retained receipts and all ambiguity; it cannot undo a prior apply.

## Wrapper compatibility and rollback

Ordinary `nest::puppet::run` callers still receive the historical wrapper mapping
of native 0 and 2 to process success. The explicit environment selection
`PUPPET_PRESERVE_DETAILED_EXIT=true` preserves the actual native exit instead;
false or unset keeps compatibility. Invalid selections refuse before service or
lock commands. Callers choosing the opt-in must handle 2 themselves instead of
mistaking it for failed transport or an unchanged run.

Regression tests exercise the actual shell wrapper with fake native commands
and the actual Puppet plan with Bolt's mock executor. They include applied versus
unchanged results, failed resources, unknown exits, failed transport, early
multi-target refusal and no implicit third attempt. No real agent, service,
dataset, host build or reboot is used by those tests. Rollback stops invoking
the new plan and omits the environment opt-in; it cannot undo resources changed
by a real catalog or authorize replaying an ambiguous apply.
