# Joyride browser acquisition diagnosis (historical)

The [original incident and recovery record](https://gitlab.joyfullee.me/nest/config/-/blob/8ef5cfe35ab1ef4816d644356d683a95d42c0fec/docs/joyride-browser-acquisition-diagnosis.md)
records the Joyride kickstart browser incident, the recovery performed at the
time, and the distinction between session recovery and durable source changes.
It is not a current incident, deployment procedure, or authorization to restart
Firefox or replay the original actions.

See the [Firefox secure-browser bridge](firefox-secure-browser-bridge.md) for
its maintained architecture and [Joyride TEST delivery](joyride-test-deployment.md)
for the application deployment path. Keep browser recovery separate from app
promotion, and preserve the profile, retained journals, and active work.
