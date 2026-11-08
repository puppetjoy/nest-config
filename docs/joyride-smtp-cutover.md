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

Production credential persistence and source advancement wait for all TEST
recipient checks above. Production must use its own independently revocable
credential and managed key; never copy the TEST password or add a shared fallback.
The dormant production recipe, zero replicas and TEST-only compile guard remain
unchanged in this phase. Staged source is not launch authorization. Any later
live production activation or production email requires exact new approval.

Account/send-as policy, Workspace administration, DKIM regeneration, unrelated
personal credentials and private-route writes are outside this cutover.
