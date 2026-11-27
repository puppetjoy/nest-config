# Original Telegram reliability rollout plan (historical)

The [original source-preparation plan](https://gitlab.joyfullee.me/nest/config/-/blob/6ddfd045c05483dcacc824963638215c8ca1694c/docs/telegram-reliability-rollout-plan.md)
records the pins, risks, and proposed one-attempt rollout for ^2375 and ^2341.
[Nest !757](https://gitlab.joyfullee.me/nest/config/-/merge_requests/757) merged
that preparation. Its pins, commands, and approval are not current instructions.

Use [Routine Owl delivery](hermes-managed-source-transition.md#routine-owl-delivery)
for current release, verification, and recovery. Shared gateway interruption
requires its own scope; recover an existing attempt's evidence before taking
further action. Do not replay an unknown apply, input, tool action, or send.
A healthy gateway does not prove delivery of a particular Telegram turn.
