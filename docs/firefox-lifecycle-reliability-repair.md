# Firefox lifecycle reliability repair

Request ^2170, task t_25bd9695. Original consumer: ^2167, task t_75690813.

## Observed boundary and proven defects

The installed controller and private transport matched origin/main at the start:
controller SHA256 dc3dec6e7256460c045c005bcfa9d9ec25864d014f452c0262664c097be57fdd;
transport SHA256 05b70052faf05895187716df21410719b3e46b4c8a8926cf22c90fb943cdc630.
The original consumer had a same-generation creating reservation with no context.
Its historical exception was scrubbed; neither the initiating exception nor
whether that create took effect can be retrospectively established. A fresh
request-bound acquisition succeeded. That success did not repair the consumer.

A focused regression executing the actual shipped CdpSession exchange and
Windows callback failed against baseline: a timeout closed the observer and
threw away the only channel on which a late correlated reply could arrive.
A second baseline failure showed a closed observer before send was classified
as uncertain creation rather than known not-started. Existing tests exercised
idealized native callbacks, not this complete client/controller seam.

The receipt callback also mutated in-memory identity before fsync. It now rolls
that mutation back on persistence failure. Privacy-safe creation phase, command
ID, native receipt ID and allowlisted native error code are retained; private
native messages, page content and input responses are not diagnostic evidence.

## Contract

The single bridge-owned native session and observer serialization are retained.
A creation timeout retains one outstanding command and its exact callback.
One bounded recover wait can consume that same response and durably retain its
identity. It never resends creation. Unmatched command IDs and events cannot
supply identity. Exhaustion stops with engineering repair required. Non-creation
input failures retain their existing uncertain-action/no-replay semantics.

There is no native command-result lookup after the observer process/socket has
been lost. No URL/title matching or tree subtraction is introduced. Existing
unknown creation cannot be magically adopted. The operator-only controller
refresh has a separate explicit creation-recovery operation for an already
authorized bounded new binding. It requires a new exclusive controller lease,
the exact live epoch, reservation creation ID, fresh journal digest, nonterminal
scope, no pending/uncertain input and short expiry. The old reservation and grant
are atomically retained as provenance before new admission. All input keys remain
fenced. Each scope can receive this recovery once, not a series of replacements.
The actual native window count, including unknown/unowned windows, also bounds
new creation. Owner/unrelated/unknown windows are not closed.

The authorization identifier is a provenance label, not a capability or evidence
of Joy consent. Only the local administrator with existing authority may invoke
this operation; public HTTPS commands and owner-viewer requests cannot install
a grant. The original proposal-approval path for retired-generation recovery is
unchanged. The broader repair authorization for this incident is in ^2170;
it does not authorize credentials, profile reset or application input replay.

The existing managed image build and controller-only overlay activation are the
shipping path. The overlay is extracted from the verified managed image; it is
not an ad-hoc edit of deployed source. Refresh does not restart Firefox, the
profile, geckodriver or KasmVNC. Native browser restarts still fence old IDs;
this patch does not pretend those IDs survive a new native session.

## Executed verification and operational follow-through

Baseline red tests: actual-client late-reply retention and closed-before-send
classification both failed. The additional local operator-recovery fixtures
failed before implementation. Focused lifecycle suites passed after repair.

The disposable native lifecycle canary used the actual Firefox protocol client,
with one timeout injected before reading a real native response. Late receipt
recovery, concurrent scope isolation, controller reconstruction, one bounded
missing-receipt recovery, preserved old provenance, exact terminal cleanup and
unchanged owner identity passed. No owner mounts or external network were used.
This is source-overlay fixture evidence, not installed consumer acceptance.

Bolt preflight initially failed from this isolated worktree before transport:
`./bin/bolt-wrapper inventory show owl --detail --format json` reported
`Could not find module ruby_task_helper containing task file task_helper.rb`.
`./bin/bolt-wrapper module install` resolved the declared project dependencies.
Repeating the inventory command and the documented
`./bin/bolt-wrapper command run 'id -un && hostname -f' --targets owl --stream`
passed as joy on owl. No direct SSH or ad-hoc Puppet fallback was used.

All required exact-head CI jobs passed in pipeline 11914 at
dadeb98ba16c5f4c8d476e51ab78ea58414d46d6. MR !548 merged as
2e43b765c21b5176276fbf7615d1512d3d507720. The focused lifecycle suite passed
106 tests; all ten compatibility scripts and the Node viewer suite passed.
The full native window canary additionally verified shared synthetic login,
input/screenshot isolation, no accidental sends, owner focus and exact cleanup.

The documented `nest::build::firefox` plan applied only the three changed
controller assets, passed the real Firefox/Kasm navigation/input/click/tab/PNG
smoke check and published the managed image. Pull-back by the exact registry
manifest succeeded:

- Image: registry.gitlab.joyfullee.me/nest/tools/firefox@sha256:b0e89162d5f1f90d7d701eb7afeebc5e5b6d7e8dc53dc1dc4313105f8f3c5670
- Image config: a0202e6be6ef2acc04b7052d4c33441ba04b41bc74b8a942f2184925c6f9d6a5
- Controller: ed5755809bcf91d21163c4a8cacce8ee9d1684482051db91a8f4821459c3ccce
- Endpoint: c569b05b6b2746524b9fc34c2e20505e91f1dd5470653bc81ecca0429c4a7b61
- Transport: 5f4840fe9341c43d311f0d0e3af988bc3dd71180bfa4c9506f45d40951ea9965

All three extracted payload hashes match reviewed source. Podman's additional
local RepoDigests alias a89e58bdc7f71c223dd028f73e78034889b9d4cebab48a8dd575d8b3276bb70e
was not available from the registry; it is not the shipped identity. The exact
manifest above was independently pulled successfully instead.

Managed Puppet code deployment verified the merged source in both test and
production OpenVox. No host profile service was restarted: the changed private
transport executes inside Firefox, not in the public HTTPS host adapter. The
KubeCM image pin advances the future container baseline. The accepted
controller-only managed overlay operation avoids an unnecessary Recreate of
the live browser/profile and installs the same extracted payload.

Before activation, this task's distinct native window confirmed the exact
existing Muse URL and title Chat — Luna, readable chat and an enabled Message
composer. That is supplementary client evidence, not recovery of the other
scope. Installed controller parity, original consumer recovery and a genuinely
resumed original owner remain pending. No Luna client acceptance or member
mutation is claimed by this report.
