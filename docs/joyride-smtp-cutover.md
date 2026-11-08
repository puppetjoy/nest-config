# Dedicated Joyride SMTP cutover

## TEST integration

TEST authenticates as `joy@joyridedc.com` to `smtp.gmail.com`, port 587,
using STARTTLS and the application's normal certificate and hostname validation.
Application and worker processes explicitly receive
`DEFAULT_FROM_EMAIL=Friday Night Joyride <hello@joyridedc.com>`.
The sender override requires application MR !100; the legacy unset default is
unchanged. Public host, username and sender belong in ordinary environment
configuration, not in encrypted credentials.

The private TEST Hiera scope supplies
`nest::service::joyride::test_smtp_password`, converted to `Sensitive[String]`.
The TEST-only service contract requires a nonempty value and renders it into
`joyride-test-runtime` as `EMAIL_HOST_PASSWORD`. It never falls back to the
legacy shared-account `runtime_secrets` SMTP entries. Existing shared credentials
remain unchanged for other consumers; do not revoke or rotate them.

Preserve `MAIL_ENABLED=1` and the existing TEST recipient allowlist. These settings
do not widen private routes, frontend/content publication or deployment authority.

## Required order and acceptance

1. Require successful exact-head CI and normal approval for application, private
   Hiera and Nest configuration changes. Merge and deliver through the existing
   managed TEST paths. Do not roll a newer active backend back to an old source
   pin: bind the config image to the accepted application delivery first.
2. Render with `nest::eyrie::deploy_joyride_test` and nonempty `render_to`.
   Keep every rendered Secret and intermediate build file restricted and private;
   publish only sanitized comparisons. Verify username, sender, dedicated-secret
   equality and unchanged unrelated resources/settings.
3. Read back installed application and worker settings, image identity and TEST
   isolation. Preserve active graph, frontend/content selections and private data.
4. Send one clearly labeled actual TEST message to `joyfulskater@gmail.com`.
   Retain safe Message-ID, timestamp and SMTP result, not passwords or login codes.
   SMTP acceptance is transport evidence, not recipient delivery or acceptance.
5. Through approved recipient access or Joy's readback, verify visible From is
   `hello@joyridedc.com`, the seasonal Joyride avatar appears instead of Joy's
   personal avatar, and raw Authentication-Results show SPF PASS, DKIM PASS with
   `d=joyridedc.com`, and DMARC PASS. Published DNS is separate evidence.

## Production remains undeployed

Joy supplied actual Gmail recipient screenshots for the single TEST message.
The visible From remained `Friday Night Joyride <hello@joyridedc.com>`, the
seasonal yellow/orange Joyride avatar appeared, and Gmail's Show original
summary reported SPF PASS, DKIM PASS with domain `joyridedc.com` and DMARC PASS.
This recipient evidence, recorded by trusted steering on request ^2331, is
separate from the SMTP acceptance receipt. No resend is needed.

After that acceptance, private Hiera MR !18 stages the independently encrypted
`nest::service::joyride::production_smtp_password`, converted to
`Sensitive[String]`, only in service `joyride` / namespace `joyride` scope:
`data/kubernetes/service/joyride/joyride.yaml`. Private verification established
that production and TEST plaintext credentials differ; distinct ciphertext
alone would not establish this. Both exact temporary credential handoff files
were removed after published persistence and identity checks. No plaintext
copies or raw rendered Secret attachments are retained.

The dormant public production ConfigMap now stages the same SMTP host,
username and explicit sender as TEST. Web/worker runtime and web initializers
reference only `joyride-smtp` / `EMAIL_HOST_PASSWORD` in namespace `joyride`.
There is no optional reference or shared-account fallback. The ops container
receives no SMTP password. This is a future provisioning contract, not an
existing Kubernetes Secret: production Secret rendering/provisioning remains
behind the closed TEST-only compile boundary, as do all other production
runtime secrets. Its eventual approved implementation must populate that exact
Secret exclusively from `production_smtp_password` using managed secret
handling, reject missing/empty values, retain smtp.gmail.com port 587 STARTTLS
and normal certificate verification, and validate the then-current application
artifact's sender support. Do not reuse the stale dormant image pin for launch.
No production password is unwrapped or rendered by the current TEST class.

The existing production image pin, zero replicas, suspended jobs,
`MAIL_ENABLED=0` and TEST-only compile guard remain unchanged. Staged source is
not a launch-ready production recipe or launch authorization. Normal source
approval is required for staging merges. Any later production provisioning,
activation or production email requires exact new approval; this task performs
none of them.

Account/send-as policy, Workspace administration, DKIM regeneration, unrelated
personal credentials and private-route writes are outside this cutover.
