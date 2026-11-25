# Dedicated Joyride SMTP cutover (historical)

The [original cutover and TEST acceptance record](https://gitlab.joyfullee.me/nest/config/-/blob/7206b6ac8b41d665dcb302c6ba96b20ccaddd2ac/docs/joyride-smtp-cutover.md)
preserves the recipient verification and the former production staging plan.
Do not reuse its old image pins, send instructions, or approvals.

TEST and production now run separately. Use [TEST sign-in mail guidance](joyride-test-deployment.md#allowlisted-sign-in-email)
and the [production promotion and approval boundaries](joyride-environment-boundaries.md).
Keep environment-local SMTP credentials and the TEST recipient allowlist. The
production service uses the dedicated `joyride-smtp` reference, not the shared
account fallback. App readiness and image promotion do not prove or authorize
production mail delivery. Do not resend the historical TEST message.
