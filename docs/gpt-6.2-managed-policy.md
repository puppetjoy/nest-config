# GPT 6.2 managed profile policy

Talon selects canonical `gpt-6.2-sol`; Star selects canonical
`gpt-6.2-astra`. Both use official OpenAI Codex Responses, not app-server
threads. Talon's explicit Wizard model follows Sol. Star's fallback compressor
uses the existing `gpt-6-luna-900k` compatibility selector, resolving Luna's
verified 872000-token maximum instead of its 272000-token default. It still
sends canonical `gpt-6-luna` on the wire at the existing effort. Without this
narrow opt-in, the auxiliary feasibility check clamps the 800000 native
threshold to 263808 and the 840000 local cap to 272000. Other auxiliary and
delegation routes and profiles are unchanged.

Hermes source MR !162 qualifies exact canonical IDs using authenticated
`max_context_window`, isolated by account and provider route. Both publish
872000 tokens, versus catalog defaults of 500000 for Sol and 272000 for
Astra. Nest selects its merged source at
`e54dd758762c41e35c899e98417616bb8b18ccbd`. Its tree is identical to qualified
source `d84973444811b791ae8f7a6b195222e96b004a75`.

Both profiles use an exact provider-scoped ratio of 0.98, local fallback cap
840000 and native Responses threshold 800000. Native compaction starts with
72000 tokens below the published model bound; the fallback ceiling leaves
32000. This headroom covers output, tools and estimation uncertainty; it is
not an asserted provider-enforced output cap. Consumer Codex does not send
`max_output_tokens`. No full-window saturation test is claimed.

Star's previous native threshold of 200000 and default ratio of 0.5 would
prematurely compact the new larger usable context. These gates are raised
explicitly, not silently retained. The existing 5000-message hygiene limit
remains a separate safety gate. Gateway agent-cache idle eviction is not a
permission to discard session history. No new idle compression policy is
introduced. Local summary fallback and existing compressor helpers remain.

Talon retains explicit medium reasoning. Star remains unset in policy;
the existing Responses transport resolves unset effort to medium. Neither
profile, helpers nor delegates are promoted to maximum effort.

The active main-model alias is retired, not the old-session compatibility
resolver. Talon's `gpt-6-luna-900k` auxiliary compression alias is unrelated
and remains unchanged. Old sealed checkpoints cannot be replayed under a
different model; existing visible session history remains available.

Source qualification used each profile's own credentials and a bounded
synthetic native threshold: two checkpoints, private SessionDB close/reopen,
forced compatibility-echo tool call and tool-result continuation passed for
each canonical model. Required source pipeline 13700 passed against the
immutable source SHA. Encrypted checkpoint material and credentials are
not included in reports. Managed deployment and fresh live adoption are
separate acceptance steps; this document describes policy, not their success.

Rollback: revert only this Nest policy commit to restore Talon
`gpt-6.1-sol-900k`, Star `gpt-6-astra`, prior thresholds and source pin, then
use normal deployment/apply. Preserve the existing Broker pin and any newer
accepted source changes. Never delete sessions, credentials, memories or
pending delivery records to perform rollback.
