# Owl Firefox and PatternKit memory investigation

Request ^2240; observations on 2026-11-02 UTC. Work remains in progress.

## Before repair: independent accounting

Process memory below is proportional set size (PSS), not additive RSS.
Container cgroup totals are an independent accounting view; do not add them
to process memory. Shared memory is included in the cgroup file category,
not an additional category.

| Component | Secure Firefox | PatternKit Firefox |
| --- | ---: | ---: |
| Container memory.current | 10.159 GiB | 2.143 GiB |
| Xvnc PSS | 3241.12 MiB | 1773.92 MiB |
| Firefox parent PSS | 695.91 MiB | 134.58 MiB |
| RDD decoder PSS | 4867.18 MiB | 5.71 MiB |
| GPU process PSS | 339.54 MiB | 62.53 MiB |
| Isolated web content PSS | 821.09 MiB | 20.59 MiB |
| WebExtensions PSS | 233.37 MiB | 87.69 MiB |
| Sum of container process PSS | 10299.98 MiB | 2159.50 MiB |

Remaining processes include privileged/spare content, socket/utility services,
accessibility, window management and browser controllers. PatternKit's OAuth
proxy is a separate roughly 12 MiB workload. The adjacent conmon cgroups are
not browser-container accounting.

Secure decoder residency was predominantly 6079 mozilla-ipc memfd mappings,
not ordinary heap cache. Both Xvnc processes were predominantly private
anonymous memory, not shared framebuffers. Initial command geometry was
1365x768; the actual secure display had resized to 2272x1174. PatternKit was
1365x768. No display resolution or quality was reduced.

Both deployed Xvnc binaries report KasmVNC 1.5.0 and have SHA256
`44dcc3bca46077862e30a1c29e3f0a2aa650494bc73ff3353686766f0d220e94`.
The container images differ; matching Xvnc does not imply matching controllers
or all other image contents. Both Firefox installations report version 157.0.

## Reproduced VNC cause: TLS ownership on ordinary HTTP exits

The exact shipped binaries were tested separately inside each workload using
only a new disposable X display, loopback port, synthetic certificate and
synthetic document. No production display, browser profile or page was read or
changed by this test.

`files/firefox-browser/smoke-kasmvnc-memory.py` makes 300 successful HTTPS GETs
against that disposable server and compares the final 100 requests after
warm-up. Both unmodified binaries fail its bounded-growth assertion:

| Exact binary environment | PSS at startup | PSS after 300 GETs | Final 100 GET growth |
| --- | ---: | ---: | ---: |
| Secure Firefox image | 39691 KiB | 65046 KiB | 8344 KiB |
| PatternKit image | 38680 KiB | 64220 KiB | 8424 KiB |

KasmVNC `common/network/websocket.c` allocates `SSL` and `SSL_CTX` for each
TLS connection. Ordinary HTTP and failed-handshake paths call `free_ws_ctx`
without the successful WebSocket teardown's `ws_socket_free`. The context
buffers are freed, but its OpenSSL objects are not. This is a genuine
per-request leak, not a required display allocation or merely free retained
allocator pages.

PatternKit's numeric allocator metadata showed about 2.056 GB of heap system
allocation with less than 1 MB listed free. XRes reported only about 4.46 MB
of live pixmaps. Bounded stack inspection found the surviving Xvnc threads
waiting in the X event loop, WebSocket accept and UDP event loop. No raw heap,
page content, credential or cookie dump was taken.

The configured HTTPS readiness probes run every 5 seconds in both workloads;
PatternKit also uses HTTPS liveness every 20 seconds. Extrapolating the measured
post-warm-up slopes gives roughly 58.67 MiB/hour for secure Firefox readiness
and 74.04 MiB/hour for PatternKit's combined probes. At the historical process
ages, that predicts about 3.02 GiB and 1.80 GiB respectively, consistent with
the observed VNC footprints. This is explanatory extrapolation, not measured
repair savings or proof that every allocated byte has the same origin.

Earlier synthetic Tight/WebP framebuffer tests transferred real data, including
high-entropy updates exceeding 8 MB per cycle. Their PSS stayed below 50 MiB
through reconnects with default settings, a smaller arena count and single
encoding thread. Those controls did not reproduce production growth. Changing
thread counts, resolution, quality or arbitrary resource limits is not the fix.

## Narrow source correction

The existing managed KasmVNC build script adds TLS-object release to the common
context destructor. Successful WebSocket cleanup already nulls those pointers,
so the destructor does not release them twice. Socket closure remains with
its existing owner; closing it in the common destructor would risk a later
double-close after a failed handshake.

The permanent disposable regression is installed by the existing Firefox image
class and invoked by its normal smoke test. The managed candidate build uses
the existing `nest::build::firefox` plan with an immutable base image and frozen
Portage repository revisions. Production rollout remains subject to continuity
and authorization gates; source preparation is not installed acceptance.

## OOM and continuity timeline

At 22:37:21 UTC the kernel recorded a global OOM and selected the old secure
RDD process. The browser container was killed as an OOM group and Kubernetes
automatically restarted it at 22:37:27 UTC. This investigation did not request
that restart. The lower post-restart memory is not a fix or claimed savings.
PatternKit already had a previous OOMKilled termination before investigation.

Supported tools returned `FIREFOX_IDENTITY_LOST` before and after the OOM.
Joy then explicitly authorized one controller-only reconciliation. Fresh
canonical instruction, journal digest, only the exact historical legacy
fingerprints, exclusive idle endpoint and unoccupied native driver were checked
before execution through inventory-backed Bolt. Supported status/lifecycle and
navigation/readback now work. Firefox, geckodriver and Xvnc process start
identities were unchanged by the controller refresh. The original journal
bundle is immutable mode 0400 with a verified digest; legacy bytes and their
original unresolved states remain unchanged. Input replay remains disabled.

Only this task's newly acquired window was used for a public example page and
a short public sample video. A supported screenshot confirmed completed video
playback. The fresh RDD process remained around 23–33 MiB PSS in these bounded
checks; they do not reproduce or resolve the old multi-GiB decoder state.
A DOM query and a coordinate replay click returned generic uncertain-outcome
errors; neither was replayed. Fresh native journal inspection found no new
unresolved native action records. Do not report these failed operations as
successful interaction coverage.

Both profile homes are PVC-backed, and compressed sessionstore backup files
exist. That alone does not guarantee native window/controller continuity across
a container replacement. No Firefox, geckodriver, VNC or production container
restart is authorized by the controller-only decision. No rollout has occurred.

## Verification status

- RED: the permanent regression fails against both actual deployed binaries
  on post-warm-up HTTPS memory growth, not setup failure.
- Syntax: changed shell scripts and Python compile checks pass; `git diff
  --check` passes. No PDK/unit suite was requested or run locally.
- GREEN: the managed candidate's permanent regression completed 300 successful
  HTTPS requests with only 40 KiB PSS growth in the final 100, versus 8344 KiB
  on the unmodified secure binary and 8424 KiB on PatternKit's binary.
- Its normal image smoke passed browser navigation, DOM/text readback,
  input/click, tabs and PNG capture. The build also rechecked frozen repository
  revisions successfully.
- Publication initially failed because the root Podman registry context lacked
  access. Re-authenticating that context as Talon with Talon's existing runtime
  credential and rerunning only the existing managed publisher resolved it.
  The published immutable candidate was pulled back and inspected:
  `registry.gitlab.joyfullee.me/nest/tools/firefox@sha256:8b64b477220c6d1121f8fdc45dabb3a4d0ff854bbcb9e4a53b5266807aeaa87c`;
  config/image ID `85d5b3ee5e0e2fa9e17feac3feb8e332a0e433ee8db693e4d2d270435154d064`.
- Extended candidate check passed 3300 successful HTTPS GETs and 33 real
  TLS-WebSocket/RFB reconnects carrying 138378240 raw framebuffer bytes, with
  unchanged 1365x768 geometry. The final 300 GETs were paced one second apart
  across five minutes. Between requests 1000 and 3000, PSS rose just 70 KiB and
  anonymous residency 56 KiB; anonymous residency did not grow in the final
  100 requests. Final PSS fell as shared residency changed; that fall is not
  claimed as an additional private-memory saving.
- Candidate installed build/smoke script SHA256 values match the committed
  source. The standalone extended synthetic verifier is retained as this
  task's downloadable `reproduce-kasmvnc-tls-framebuffer.py` attachment.
- Source CI/merge, authorized live rollout and measured production savings
  remain open. KubeCM pin changes are staged, not deployed.
- The old RDD decoder cause remains unproven; preserve that distinction from
  the independently reproduced VNC leak.

Private raw evidence and numeric diagnostic scripts remain mode-restricted in
`.local/browser-memory-2240/` in this task's isolated worktree. They are not
publication material. Reports exclude owner page contents and sensitive URLs.
